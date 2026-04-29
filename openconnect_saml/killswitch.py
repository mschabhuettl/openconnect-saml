"""Kill-switch — blocks all non-VPN traffic.

Two platform-specific backends share a common ``KillSwitch`` API:

- **Linux (iptables)** — production-quality. Creates a dedicated
  ``OPENCONNECT_SAML_KILLSWITCH`` chain jumped to from ``OUTPUT``,
  with optional ip6tables mirror.
- **macOS (pf)** — *experimental*. Loads a self-contained pf anchor
  (``openconnect-saml-killswitch``) via ``pfctl -a``. Doesn't touch
  ``/etc/pf.conf``; rules disappear cleanly on disable.

Other platforms still raise ``KillSwitchNotSupported``.

Design goals:

- **Idempotent**: enable() twice is safe; disable() when nothing is
  installed is a no-op.
- **Explicit**: nothing happens unless the user asks.
- **Recoverable**: ``openconnect-saml killswitch disable`` always
  works, even if the VPN process crashed.
- **Least privilege**: uses ``sudo``/``doas`` only when needed.
"""

from __future__ import annotations

import ipaddress
import platform
import shutil
import socket
import subprocess  # nosec
from dataclasses import dataclass
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()

CHAIN_NAME = "OPENCONNECT_SAML_KILLSWITCH"
PF_ANCHOR_NAME = "openconnect-saml-killswitch"
DEFAULT_VPN_PORT = 443
DEFAULT_VPN_INTERFACES = ("tun+", "utun+", "ppp+")
# pf interface globs — pf doesn't allow the iptables-style ``+`` wildcard,
# so we enumerate plausible tunnel device names explicitly.
DEFAULT_PF_TUNNEL_INTERFACES = ("utun0", "utun1", "utun2", "utun3", "utun4", "utun5")


class KillSwitchError(Exception):
    """Raised when a kill-switch operation fails."""


class KillSwitchNotSupported(KillSwitchError):
    """Raised when the kill-switch feature is unavailable on this platform."""


@dataclass
class KillSwitchConfig:
    """Configuration for the kill-switch.

    Attributes
    ----------
    server_host : str or None
        The VPN server host or URL. Resolved to an IP and allowlisted.
    server_port : int
        The VPN server port (default 443).
    dns_servers : list[str]
        Resolver IPs allowlisted so name resolution keeps working before
        the VPN is up. If empty, assumes the VPN provides DNS.
    allow_lan : bool
        Allow RFC1918 LAN traffic on non-tun interfaces.
    ipv6 : bool
        Whether to also manage ip6tables rules. Default True.
    sudo : str or None
        Privilege escalation binary to prefix commands with. If ``None``,
        autodetects doas/sudo. Set to empty string to run without sudo.
    """

    server_host: str | None = None
    server_port: int = DEFAULT_VPN_PORT
    dns_servers: list[str] | None = None
    allow_lan: bool = False
    ipv6: bool = True
    sudo: str | None = None

    def __post_init__(self):
        if self.dns_servers is None:
            self.dns_servers = []


def _platform_check() -> None:
    if platform.system() not in ("Linux", "Darwin"):
        raise KillSwitchNotSupported(
            f"Kill-switch is only supported on Linux (iptables) and macOS (pf); "
            f"detected: {platform.system()}"
        )


def _backend_name() -> str:
    """Return the kill-switch backend identifier for the current platform."""
    return "pf" if platform.system() == "Darwin" else "iptables"


def _find_privilege_tool(explicit: str | None) -> str | None:
    """Resolve the sudo/doas binary to use (or empty → no escalation)."""
    if explicit == "":
        return None
    if explicit:
        path = shutil.which(explicit)
        if not path:
            raise KillSwitchError(f"Requested privilege tool '{explicit}' not found in PATH")
        return path
    # Autodetect: prefer doas (lighter), then sudo
    for candidate in ("doas", "sudo"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _resolve_server_ips(host: str) -> list[str]:
    """Resolve a server address (URL or bare host) to one or more IPs.

    Returns a list of unique IP strings (both v4 and v6 when available).
    """
    parsed = urlparse(host if "://" in host else f"https://{host}")
    hostname = parsed.hostname or host
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise KillSwitchError(
            f"Cannot resolve VPN server '{hostname}': {exc}. "
            "Configure --ks-allow-dns to permit DNS before enabling."
        ) from exc
    ips = sorted({info[4][0] for info in infos})
    return ips


def _is_ipv6(ip: str) -> bool:
    try:
        return isinstance(ipaddress.ip_address(ip), ipaddress.IPv6Address)
    except ValueError:
        return False


class KillSwitch:
    """iptables-based kill-switch controller."""

    def __init__(self, config: KillSwitchConfig):
        self.config = config
        self._sudo = _find_privilege_tool(config.sudo)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enable(self) -> None:
        """Install kill-switch rules. Idempotent."""
        _platform_check()
        if _backend_name() == "pf":
            return self._pf_enable()
        return self._iptables_enable()

    def disable(self, silent: bool = False) -> None:
        """Remove kill-switch rules. Idempotent."""
        _platform_check()
        if _backend_name() == "pf":
            return self._pf_disable(silent=silent)
        return self._iptables_disable(silent=silent)

    def is_active(self) -> bool:
        """Check whether the kill-switch is currently installed."""
        _platform_check()
        if _backend_name() == "pf":
            return self._pf_is_active()
        return self._chain_exists("iptables")

    def status(self) -> dict:
        """Return a dict describing the current kill-switch state."""
        _platform_check()
        if _backend_name() == "pf":
            return self._pf_status()
        state = {
            "backend": "iptables",
            "active": self.is_active(),
            "ipv4_chain": self._chain_exists("iptables"),
            "ipv6_chain": self._chain_exists("ip6tables") if self.config.ipv6 else False,
        }
        if state["active"]:
            state["rules"] = self._list_chain_rules("iptables")
        return state

    # ------------------------------------------------------------------
    # iptables backend (Linux)
    # ------------------------------------------------------------------

    def _iptables_enable(self) -> None:
        self._ensure_iptables_available()

        if self._chain_exists("iptables"):
            logger.info("Kill-switch already active — refreshing rules")
            self._iptables_disable(silent=True)

        server_ips: list[str] = []
        if self.config.server_host:
            try:
                server_ips = _resolve_server_ips(self.config.server_host)
                logger.info(
                    "Resolved VPN server for kill-switch",
                    host=self.config.server_host,
                    ips=server_ips,
                )
            except KillSwitchError as exc:
                logger.error("Cannot resolve VPN server for kill-switch", error=str(exc))
                raise

        self._install_chain("iptables", server_ips=[ip for ip in server_ips if not _is_ipv6(ip)])
        if self.config.ipv6:
            self._install_chain("ip6tables", server_ips=[ip for ip in server_ips if _is_ipv6(ip)])

        logger.info("Kill-switch enabled", chain=CHAIN_NAME)

    def _iptables_disable(self, silent: bool = False) -> None:
        self._ensure_iptables_available()

        removed = False
        for tool in ("iptables", "ip6tables" if self.config.ipv6 else None):
            if not tool:
                continue
            if self._chain_exists(tool):
                self._remove_chain(tool)
                removed = True

        if removed and not silent:
            logger.info("Kill-switch disabled")
        elif not removed and not silent:
            logger.info("Kill-switch was not active")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_iptables_available(self) -> None:
        if not shutil.which("iptables"):
            raise KillSwitchError(
                "iptables command not found. Install iptables "
                "(package: 'iptables' on Debian/Ubuntu/Arch/Fedora)."
            )

    def _run(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        full_cmd = ([self._sudo] if self._sudo else []) + cmd
        logger.debug("Kill-switch running command", cmd=full_cmd)
        result = subprocess.run(  # nosec
            full_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise KillSwitchError(
                f"Command {' '.join(full_cmd)} failed "
                f"(exit {result.returncode}): {result.stderr.strip()}"
            )
        return result

    def _chain_exists(self, tool: str) -> bool:
        full_cmd = ([self._sudo] if self._sudo else []) + [tool, "-nL", CHAIN_NAME]
        result = subprocess.run(  # nosec
            full_cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _list_chain_rules(self, tool: str) -> list[str]:
        result = self._run([tool, "-S", CHAIN_NAME], check=False)
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.splitlines() if line.strip()]

    def _install_chain(self, tool: str, server_ips: list[str]) -> None:
        """Create the kill-switch chain and install rules."""
        # Create the chain (idempotent via -N; error is fine if already exists)
        self._run([tool, "-N", CHAIN_NAME], check=False)
        self._run([tool, "-F", CHAIN_NAME])  # Flush in case of partial state

        # Allow established/related (so replies to outbound connections work)
        self._run(
            [
                tool,
                "-A",
                CHAIN_NAME,
                "-m",
                "conntrack",
                "--ctstate",
                "ESTABLISHED,RELATED",
                "-j",
                "ACCEPT",
            ]
        )

        # Allow loopback
        self._run([tool, "-A", CHAIN_NAME, "-o", "lo", "-j", "ACCEPT"])

        # Allow output via tun/utun/ppp interfaces
        for iface in DEFAULT_VPN_INTERFACES:
            self._run([tool, "-A", CHAIN_NAME, "-o", iface, "-j", "ACCEPT"])

        # Allow DNS to configured resolvers
        for dns in self.config.dns_servers or []:
            if (_is_ipv6(dns) and tool == "ip6tables") or (
                not _is_ipv6(dns) and tool == "iptables"
            ):
                for proto in ("udp", "tcp"):
                    self._run(
                        [
                            tool,
                            "-A",
                            CHAIN_NAME,
                            "-p",
                            proto,
                            "-d",
                            dns,
                            "--dport",
                            "53",
                            "-j",
                            "ACCEPT",
                        ]
                    )

        # Allow traffic to the VPN server
        for ip in server_ips:
            self._run(
                [
                    tool,
                    "-A",
                    CHAIN_NAME,
                    "-p",
                    "tcp",
                    "-d",
                    ip,
                    "--dport",
                    str(self.config.server_port),
                    "-j",
                    "ACCEPT",
                ]
            )
            # Also UDP for DTLS / OpenConnect keepalives
            self._run(
                [
                    tool,
                    "-A",
                    CHAIN_NAME,
                    "-p",
                    "udp",
                    "-d",
                    ip,
                    "--dport",
                    str(self.config.server_port),
                    "-j",
                    "ACCEPT",
                ]
            )

        # Allow LAN traffic if requested (RFC1918 for v4, link-local for v6)
        if self.config.allow_lan:
            if tool == "iptables":
                for lan in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
                    self._run([tool, "-A", CHAIN_NAME, "-d", lan, "-j", "ACCEPT"])
            else:
                for lan in ("fc00::/7", "fe80::/10"):
                    self._run([tool, "-A", CHAIN_NAME, "-d", lan, "-j", "ACCEPT"])

        # REJECT everything else (use icmp-host-unreachable for clearer failure mode)
        reject_opt = "icmp-host-unreachable" if tool == "iptables" else "icmp6-adm-prohibited"
        self._run(
            [
                tool,
                "-A",
                CHAIN_NAME,
                "-j",
                "REJECT",
                "--reject-with",
                reject_opt,
            ]
        )

        # Insert jump from OUTPUT to our chain (at top so it runs first).
        # Check if already present; if not, insert at position 1.
        self._run([tool, "-D", "OUTPUT", "-j", CHAIN_NAME], check=False)
        self._run([tool, "-I", "OUTPUT", "1", "-j", CHAIN_NAME])

    def _remove_chain(self, tool: str) -> None:
        """Delete the jump from OUTPUT, flush and delete the chain."""
        # Remove jump — may fail if already gone; that's fine
        self._run([tool, "-D", "OUTPUT", "-j", CHAIN_NAME], check=False)
        # Flush and drop the chain
        self._run([tool, "-F", CHAIN_NAME], check=False)
        self._run([tool, "-X", CHAIN_NAME], check=False)

    # ------------------------------------------------------------------
    # pf backend (macOS) — experimental
    # ------------------------------------------------------------------

    def _ensure_pfctl_available(self) -> None:
        if not shutil.which("pfctl"):
            raise KillSwitchError(
                "pfctl command not found. macOS ships pf by default — check your "
                "PATH or run /sbin/pfctl directly."
            )

    def _pf_render_rules(self, server_ips: list[str]) -> str:
        """Render the pf anchor ruleset as text suitable for ``pfctl -f -``."""
        lines: list[str] = [
            "# openconnect-saml kill-switch (auto-generated)",
            "set skip on lo0",
            "pass out quick on lo0 all",
        ]
        # Always allow established (pf does this automatically with `keep state`)
        for iface in DEFAULT_PF_TUNNEL_INTERFACES:
            lines.append(f"pass out quick on {iface} all keep state")
        # DNS allow-list
        for dns in self.config.dns_servers or []:
            if _is_ipv6(dns):
                continue  # pf rules below default to v4; v6 needs separate
            lines.append(f"pass out quick proto {{ udp tcp }} to {dns} port 53 keep state")
        # VPN server allow-list
        for ip in server_ips:
            if _is_ipv6(ip):
                continue  # macOS-only IPv6 still served by separate stanza
            lines.append(
                f"pass out quick proto {{ tcp udp }} to {ip} "
                f"port {self.config.server_port} keep state"
            )
        # LAN allow-list
        if self.config.allow_lan:
            for lan in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
                lines.append(f"pass out quick to {lan} keep state")
        # Default-deny
        lines.append("block return-icmp out all")
        return "\n".join(lines) + "\n"

    def _pf_enable(self) -> None:
        self._ensure_pfctl_available()

        server_ips: list[str] = []
        if self.config.server_host:
            try:
                server_ips = _resolve_server_ips(self.config.server_host)
                logger.info(
                    "Resolved VPN server for kill-switch",
                    host=self.config.server_host,
                    ips=server_ips,
                )
            except KillSwitchError as exc:
                logger.error("Cannot resolve VPN server for kill-switch", error=str(exc))
                raise

        rules = self._pf_render_rules(server_ips=server_ips)

        # Make sure pf itself is enabled — pf is off by default on macOS.
        self._run(["pfctl", "-e"], check=False)

        # Load our anchor with the rules. ``pfctl -a anchor -f -`` reads from stdin.
        full_cmd = ([self._sudo] if self._sudo else []) + [
            "pfctl",
            "-a",
            PF_ANCHOR_NAME,
            "-f",
            "-",
        ]
        result = subprocess.run(  # nosec
            full_cmd,
            input=rules,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise KillSwitchError(
                f"pfctl failed to load anchor '{PF_ANCHOR_NAME}' "
                f"(exit {result.returncode}): {result.stderr.strip()}"
            )

        logger.info("Kill-switch enabled", anchor=PF_ANCHOR_NAME, backend="pf")

    def _pf_disable(self, silent: bool = False) -> None:
        self._ensure_pfctl_available()

        if not self._pf_is_active():
            if not silent:
                logger.info("Kill-switch was not active")
            return

        # Flush all rules from our anchor — leaves the empty anchor entry behind,
        # which is harmless. The anchor naturally goes away on reboot.
        self._run(["pfctl", "-a", PF_ANCHOR_NAME, "-F", "all"], check=False)

        if not silent:
            logger.info("Kill-switch disabled", anchor=PF_ANCHOR_NAME)

    def _pf_is_active(self) -> bool:
        # Check whether our anchor has any rules loaded.
        result = self._run(
            ["pfctl", "-a", PF_ANCHOR_NAME, "-sr"],
            check=False,
        )
        if result.returncode != 0:
            return False
        return bool(result.stdout.strip())

    def _pf_status(self) -> dict:
        result = self._run(["pfctl", "-a", PF_ANCHOR_NAME, "-sr"], check=False)
        rules: list[str] = []
        if result.returncode == 0:
            rules = [line for line in result.stdout.splitlines() if line.strip()]
        return {
            "backend": "pf",
            "active": bool(rules),
            "anchor": PF_ANCHOR_NAME,
            "rules": rules,
        }


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------


def handle_killswitch_command(args) -> int:
    """Dispatch the ``killswitch`` subcommand."""
    action = getattr(args, "killswitch_action", None)

    dns_servers = getattr(args, "ks_allow_dns", None) or []
    config = KillSwitchConfig(
        server_host=getattr(args, "server", None),
        server_port=getattr(args, "ks_port", DEFAULT_VPN_PORT) or DEFAULT_VPN_PORT,
        dns_servers=list(dns_servers),
        allow_lan=getattr(args, "ks_allow_lan", False),
        ipv6=not getattr(args, "ks_no_ipv6", False),
        sudo=getattr(args, "ks_sudo", None),
    )

    try:
        ks = KillSwitch(config)
    except KillSwitchNotSupported as exc:
        print(f"Error: {exc}")
        return 2

    try:
        if action == "enable":
            if not config.server_host:
                print(
                    "Error: --server is required for 'killswitch enable' so we can "
                    "allowlist the VPN endpoint."
                )
                return 1
            ks.enable()
            print("✓ Kill-switch enabled.")
            print("  All non-VPN traffic will be blocked until the tunnel is up.")
            print("  Disable with: openconnect-saml killswitch disable")
            return 0
        elif action == "disable":
            ks.disable()
            print("✓ Kill-switch disabled.")
            return 0
        elif action == "status":
            state = ks.status()
            backend = state.get("backend", "iptables")
            if state["active"]:
                print(f"Kill-switch: ACTIVE  ({backend})")
                if backend == "iptables":
                    print(f"  IPv4 chain: {'yes' if state.get('ipv4_chain') else 'no'}")
                    print(f"  IPv6 chain: {'yes' if state.get('ipv6_chain') else 'no'}")
                else:
                    print(f"  pf anchor: {state.get('anchor', PF_ANCHOR_NAME)}")
                if state.get("rules"):
                    print("  Rules:")
                    for rule in state["rules"]:
                        print(f"    {rule}")
            else:
                print(f"Kill-switch: inactive  ({backend})")
            return 0
        else:
            print(f"Unknown killswitch action: {action}")
            return 1
    except KillSwitchNotSupported as exc:
        print(f"Error: {exc}")
        return 2
    except KillSwitchError as exc:
        print(f"Error: {exc}")
        return 1
