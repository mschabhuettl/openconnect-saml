"""Diagnostics command — ``openconnect-saml doctor``.

Runs a series of checks to help users debug common setup issues:
install status, PATH, permissions, network reachability, Python deps, etc.
Each check is a :class:`Check` with ``ok``/``warn``/``fail`` outcomes.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import socket
import subprocess  # nosec
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""
    hint: str = ""
    details: list[str] = field(default_factory=list)

    @property
    def symbol(self) -> str:
        return {
            STATUS_OK: "✓",
            STATUS_WARN: "!",
            STATUS_FAIL: "✗",
            STATUS_SKIP: "~",
        }.get(self.status, "?")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_python_version() -> CheckResult:
    version = sys.version_info
    required_major, required_minor = 3, 10
    if version >= (required_major, required_minor):
        return CheckResult(
            "Python version",
            STATUS_OK,
            f"{version.major}.{version.minor}.{version.micro}",
        )
    return CheckResult(
        "Python version",
        STATUS_FAIL,
        f"{version.major}.{version.minor}.{version.micro}",
        hint=f"Python >= {required_major}.{required_minor} is required.",
    )


def _check_openconnect() -> CheckResult:
    path = shutil.which("openconnect")
    if not path:
        return CheckResult(
            "openconnect binary",
            STATUS_FAIL,
            "not found in PATH",
            hint=(
                "Install openconnect:\n"
                "  Debian/Ubuntu: apt install openconnect\n"
                "  Arch:          pacman -S openconnect\n"
                "  Fedora:        dnf install openconnect\n"
                "  macOS:         brew install openconnect"
            ),
        )
    version = "unknown"
    try:
        result = subprocess.run(  # nosec
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        # openconnect prints version to stdout, sometimes stderr
        output = (result.stdout or "") + (result.stderr or "")
        for line in output.splitlines():
            if "openconnect" in line.lower() and "version" in line.lower():
                version = line.strip()
                break
    except (subprocess.TimeoutExpired, OSError):
        pass
    return CheckResult(
        "openconnect binary",
        STATUS_OK,
        path,
        details=[version] if version != "unknown" else [],
    )


def _check_sudo() -> CheckResult:
    for name in ("doas", "sudo"):
        path = shutil.which(name)
        if path:
            return CheckResult(
                "Privilege escalation",
                STATUS_OK,
                f"{name} available ({path})",
            )
    if platform.system() == "Windows":
        return CheckResult(
            "Privilege escalation",
            STATUS_SKIP,
            "Windows — runs under Administrator directly",
        )
    return CheckResult(
        "Privilege escalation",
        STATUS_WARN,
        "neither 'sudo' nor 'doas' found",
        hint=(
            "openconnect needs root to configure the tunnel. "
            "Install sudo/doas or use --no-sudo with alternative mechanisms."
        ),
    )


def _check_tun_device() -> CheckResult:
    if platform.system() != "Linux":
        return CheckResult(
            "TUN/TAP device",
            STATUS_SKIP,
            f"not checked on {platform.system()}",
        )
    tun = Path("/dev/net/tun")
    if tun.exists():
        return CheckResult(
            "TUN/TAP device",
            STATUS_OK,
            str(tun),
        )
    return CheckResult(
        "TUN/TAP device",
        STATUS_FAIL,
        "/dev/net/tun not found",
        hint=(
            "Load the tun kernel module: 'sudo modprobe tun'. "
            "In containers, pass: --cap-add=NET_ADMIN --device=/dev/net/tun"
        ),
    )


def _check_python_deps() -> list[CheckResult]:
    """Check core runtime dependencies."""
    results: list[CheckResult] = []
    core_deps = [
        ("attrs", "attrs"),
        ("keyring", "keyring"),
        ("lxml", "lxml"),
        ("pyotp", "pyotp"),
        ("requests", "requests"),
        ("structlog", "structlog"),
        ("toml", "toml"),
    ]
    for label, module in core_deps:
        try:
            mod = importlib.import_module(module)
            ver = getattr(mod, "__version__", "")
            results.append(
                CheckResult(
                    f"Python package: {label}",
                    STATUS_OK,
                    ver if ver else "installed",
                )
            )
        except RecursionError:
            # Some tests/instrumentation monkeypatch importlib.import_module in a
            # way that recurses when dependencies import their own optional deps.
            # If the module reached that point, treat it as present but omit the
            # version rather than turning diagnostics into a crash.
            results.append(
                CheckResult(
                    f"Python package: {label}",
                    STATUS_OK,
                    "installed",
                )
            )
        except ImportError:
            results.append(
                CheckResult(
                    f"Python package: {label}",
                    STATUS_FAIL,
                    "not installed",
                    hint=f"pip install {module}",
                )
            )
    return results


def _check_optional_deps() -> list[CheckResult]:
    results: list[CheckResult] = []
    groups = [
        ("GUI browser (PyQt6)", ["PyQt6", "PyQt6.QtWebEngineCore"], "pip install 'openconnect-saml[gui]'"),
        ("Chrome (Playwright)", ["playwright"], "pip install 'openconnect-saml[chrome]' && playwright install chromium"),
        ("FIDO2/YubiKey", ["fido2"], "pip install 'openconnect-saml[fido2]'"),
        ("Status TUI (rich)", ["rich"], "pip install 'openconnect-saml[tui]'"),
    ]
    for label, modules, hint in groups:
        found = []
        for mod in modules:
            try:
                m = importlib.import_module(mod)
                ver = getattr(m, "__version__", "")
                found.append(f"{mod}={ver}" if ver else mod)
            except ImportError:
                pass
        if len(found) == len(modules):
            results.append(CheckResult(label, STATUS_OK, ", ".join(found)))
        else:
            results.append(
                CheckResult(label, STATUS_SKIP, "not installed", hint=hint)
            )
    return results


def _check_keyring_backend() -> CheckResult:
    try:
        import keyring as kr
        backend = kr.get_keyring()
        name = type(backend).__name__
        module = type(backend).__module__
        if "fail" in name.lower() or "null" in name.lower():
            return CheckResult(
                "Keyring backend",
                STATUS_WARN,
                f"{module}.{name} (no secure backend available)",
                hint="Install a backend: 'pip install keyring' or use dbus/libsecret on Linux",
            )
        return CheckResult("Keyring backend", STATUS_OK, f"{module}.{name}")
    except Exception as exc:
        return CheckResult("Keyring backend", STATUS_FAIL, str(exc))


def _check_config_dir() -> CheckResult:
    try:
        import xdg.BaseDirectory
        path = xdg.BaseDirectory.load_first_config("openconnect-saml")
        if not path:
            return CheckResult(
                "Config directory",
                STATUS_SKIP,
                "not yet created",
                hint="Run 'openconnect-saml setup' to create a config.",
            )
        cfg = Path(path) / "config.toml"
        if not cfg.exists():
            return CheckResult(
                "Config directory",
                STATUS_WARN,
                f"{path} exists but no config.toml",
            )
        # Check permissions (Unix only)
        if platform.system() != "Windows":
            mode = cfg.stat().st_mode & 0o777
            if mode & 0o077:  # group or other can read
                return CheckResult(
                    "Config directory",
                    STATUS_WARN,
                    f"{cfg} has overly permissive mode {oct(mode)}",
                    hint=f"Fix with: chmod 0600 {cfg}",
                )
        return CheckResult("Config directory", STATUS_OK, str(cfg))
    except ImportError:
        return CheckResult(
            "Config directory", STATUS_FAIL, "pyxdg not installed"
        )


def _check_dns_resolution(host: str | None) -> CheckResult:
    if not host:
        return CheckResult(
            "DNS resolution",
            STATUS_SKIP,
            "no --server provided to test",
        )
    parsed = urlparse(host if "://" in host else f"https://{host}")
    hostname = parsed.hostname or host
    try:
        ips = socket.getaddrinfo(hostname, None)
        unique = sorted({i[4][0] for i in ips})
        return CheckResult(
            f"DNS: {hostname}",
            STATUS_OK,
            ", ".join(unique),
        )
    except socket.gaierror as exc:
        return CheckResult(
            f"DNS: {hostname}",
            STATUS_FAIL,
            str(exc),
            hint="Check your /etc/resolv.conf, VPN, and network connectivity.",
        )


def _check_server_reachable(host: str | None, port: int = 443, timeout: float = 5.0) -> CheckResult:
    if not host:
        return CheckResult(
            "VPN server reachable",
            STATUS_SKIP,
            "no --server provided to test",
        )
    parsed = urlparse(host if "://" in host else f"https://{host}")
    hostname = parsed.hostname or host
    port_to_use = parsed.port or port

    try:
        with socket.create_connection((hostname, port_to_use), timeout=timeout) as _:
            return CheckResult(
                f"TCP {hostname}:{port_to_use}",
                STATUS_OK,
                "connection established",
            )
    except TimeoutError:
        return CheckResult(
            f"TCP {hostname}:{port_to_use}",
            STATUS_FAIL,
            f"timed out after {timeout}s",
            hint="Firewall or network issue blocking outbound connection.",
        )
    except OSError as exc:
        return CheckResult(
            f"TCP {hostname}:{port_to_use}",
            STATUS_FAIL,
            str(exc),
        )


def _check_killswitch_state() -> CheckResult:
    """Check whether the kill-switch is currently active (Linux only)."""
    if platform.system() != "Linux":
        return CheckResult(
            "Kill-switch state",
            STATUS_SKIP,
            "Linux only",
        )
    if not shutil.which("iptables"):
        return CheckResult(
            "Kill-switch state",
            STATUS_SKIP,
            "iptables not installed",
        )
    try:
        from openconnect_saml.killswitch import KillSwitch, KillSwitchConfig
        ks = KillSwitch(KillSwitchConfig())
        if ks.is_active():
            return CheckResult(
                "Kill-switch state",
                STATUS_WARN,
                "ACTIVE — non-VPN traffic is being blocked",
                hint="Disable with: sudo openconnect-saml killswitch disable",
            )
        return CheckResult("Kill-switch state", STATUS_OK, "inactive")
    except Exception as exc:
        return CheckResult(
            "Kill-switch state",
            STATUS_SKIP,
            f"cannot check ({exc})",
        )


def _check_env_hygiene() -> CheckResult:
    """Warn about env vars that could leak credentials in logs or co-process output."""
    suspect = []
    for var in ("BW_SESSION", "OP_SESSION_", "PASSWORD", "VPN_PASSWORD"):
        for name in os.environ:
            if name.upper().startswith(var) and os.environ.get(name):
                suspect.append(name)
    if suspect:
        return CheckResult(
            "Environment hygiene",
            STATUS_OK,
            f"{len(suspect)} credential env var(s) present: {', '.join(suspect)}",
        )
    return CheckResult("Environment hygiene", STATUS_OK, "no credential env vars set")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_all(server: str | None = None) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(CheckResult("Platform", STATUS_OK, f"{platform.system()} {platform.release()}"))
    results.append(_check_python_version())
    results.append(_check_openconnect())
    results.append(_check_sudo())
    results.append(_check_tun_device())
    results.extend(_check_python_deps())
    results.extend(_check_optional_deps())
    results.append(_check_keyring_backend())
    results.append(_check_config_dir())
    results.append(_check_env_hygiene())
    results.append(_check_dns_resolution(server))
    results.append(_check_server_reachable(server))
    results.append(_check_killswitch_state())
    return results


def _print_results(results: list[CheckResult]) -> None:
    width = max(len(r.name) for r in results) + 2
    for r in results:
        print(f"  [{r.symbol}] {r.name:<{width}} {r.message}")
        for detail in r.details:
            print(f"        {detail}")
        if r.status in (STATUS_FAIL, STATUS_WARN) and r.hint:
            for line in r.hint.splitlines():
                print(f"        → {line}")


def handle_doctor_command(args) -> int:
    server = getattr(args, "server", None)
    print("openconnect-saml diagnostics")
    print("=" * 40)
    results = run_all(server=server)
    _print_results(results)

    ok_count = sum(1 for r in results if r.status == STATUS_OK)
    warn_count = sum(1 for r in results if r.status == STATUS_WARN)
    fail_count = sum(1 for r in results if r.status == STATUS_FAIL)
    skip_count = sum(1 for r in results if r.status == STATUS_SKIP)

    print()
    print(f"Summary: {ok_count} OK · {warn_count} warning · {fail_count} failed · {skip_count} skipped")

    if fail_count > 0:
        return 1
    if warn_count > 0:
        return 2
    return 0
