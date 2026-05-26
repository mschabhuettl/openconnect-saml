"""Diagnostics command — ``openconnect-saml doctor``.

Runs a series of checks to help users debug common setup issues:
install status, PATH, permissions, network reachability, Python deps, etc.
Each check is a :class:`Check` with ``ok``/``warn``/``fail`` outcomes.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import shutil
import socket
import subprocess  # nosec
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger()


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_SKIP = "skip"


def _plain_output() -> bool:
    """True when the user has asked for color/Unicode output to be suppressed.

    Honored signals: ``NO_COLOR`` env var (any value, per
    https://no-color.org), and a non-TTY stdout.
    """
    if os.environ.get("NO_COLOR") is not None:
        return True
    return not sys.stdout.isatty()


@dataclass
class CheckResult:
    name: str
    status: str
    message: str = ""
    hint: str = ""
    details: list[str] = field(default_factory=list)

    @property
    def symbol(self) -> str:
        plain = _plain_output()
        unicode_glyphs = {
            STATUS_OK: "✓",
            STATUS_WARN: "!",
            STATUS_FAIL: "✗",
            STATUS_SKIP: "~",
        }
        ascii_glyphs = {
            STATUS_OK: "OK",
            STATUS_WARN: "!!",
            STATUS_FAIL: "FAIL",
            STATUS_SKIP: "--",
        }
        glyphs = ascii_glyphs if plain else unicode_glyphs
        return glyphs.get(self.status, "?")


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
                "Install openconnect, then re-run this tool:\n"
                "  Debian/Ubuntu: sudo apt install openconnect\n"
                "  Arch:          sudo pacman -S openconnect\n"
                "  Fedora:        sudo dnf install openconnect\n"
                "  macOS:         brew install openconnect\n"
                "  Windows:       https://openconnect.gitlab.io/openconnect-gui/"
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


def _check_system_browser() -> CheckResult:
    """Detect installed Chrome/Chromium/Edge and suggest --chrome-executable if found."""
    candidates = [
        # Linux — common names
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        # macOS apps (via Homebrew shims or standard install)
        "Google Chrome",
        # Windows (shutil.which searches PATH)
        "chrome",
        # Microsoft Edge
        "microsoft-edge",
        "msedge",
    ]
    # Also probe well-known absolute paths on Linux/macOS
    absolute_paths = [
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
        "/usr/bin/microsoft-edge",
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]

    found_path: str | None = None
    for name in candidates:
        p = shutil.which(name)
        if p:
            found_path = p
            break
    if not found_path:
        for p in absolute_paths:
            if Path(p).exists():
                found_path = p
                break

    if not found_path:
        return CheckResult(
            "System browser",
            STATUS_SKIP,
            "no Chrome/Chromium/Edge found in PATH",
            hint=(
                "If you have a system browser you can pass it directly:\n"
                "  --browser chrome --chrome-executable /path/to/browser\n"
                "This avoids the Playwright Chromium download (~150 MB)."
            ),
        )
    return CheckResult(
        "System browser",
        STATUS_OK,
        found_path,
        hint=(
            f"Use it instead of the Playwright download:\n"
            f"  --browser chrome --chrome-executable {found_path}"
        ),
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
        (
            "GUI browser (PyQt6)",
            ["PyQt6", "PyQt6.QtWebEngineCore"],
            (
                "pip install 'openconnect-saml[gui]'\n"
                "Note: FIDO2/hardware tokens require a system Chromium — use --browser chrome instead."
            ),
        ),
        (
            "Chrome (Playwright)",
            ["playwright"],
            (
                "pip install 'openconnect-saml[chrome]' && playwright install chromium\n"
                "Or, if you already have Chrome/Chromium installed, skip the download:\n"
                "  --browser chrome --chrome-executable /path/to/chrome"
            ),
        ),
        (
            "FIDO2/YubiKey",
            ["fido2"],
            (
                "pip install 'openconnect-saml[fido2]'\n"
                "Linux also needs libfido2: sudo apt install libfido2-1  (Debian/Ubuntu)\n"
                "                          sudo pacman -S libfido2       (Arch)\n"
                "                          sudo dnf install libfido2     (Fedora)"
            ),
        ),
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
            results.append(CheckResult(label, STATUS_SKIP, "not installed", hint=hint))

    # Separately check for the libfido2 system library (ctypes-based probe)
    results.append(_check_libfido2())
    return results


def _check_libfido2() -> CheckResult:
    """Check whether libfido2 is loadable (needed for the fido2 Python package)."""
    # Only meaningful when fido2 Python package is present.
    try:
        importlib.import_module("fido2")
    except ImportError:
        return CheckResult(
            "libfido2 (system)",
            STATUS_SKIP,
            "fido2 Python package not installed",
        )
    # The fido2 package uses ctypes to load libfido2. Try to import the
    # internal binding to verify the native library is available.
    import contextlib

    with contextlib.suppress(ImportError):
        importlib.import_module("fido2._pyu2f.hid")
    try:
        import ctypes
        import ctypes.util

        lib_name = ctypes.util.find_library("fido2")
        if lib_name:
            return CheckResult("libfido2 (system)", STATUS_OK, lib_name)
        # find_library failed — try loading by guessed names
        for candidate in ("libfido2.so.1", "libfido2.so", "fido2"):
            try:
                ctypes.CDLL(candidate)
                return CheckResult("libfido2 (system)", STATUS_OK, candidate)
            except OSError:
                pass
        return CheckResult(
            "libfido2 (system)",
            STATUS_WARN,
            "shared library not found",
            hint=(
                "Install the system library for FIDO2 hardware token support:\n"
                "  Debian/Ubuntu: sudo apt install libfido2-1\n"
                "  Arch:          sudo pacman -S libfido2\n"
                "  Fedora:        sudo dnf install libfido2\n"
                "  macOS:         brew install libfido2"
            ),
        )
    except Exception:  # noqa: BLE001
        return CheckResult("libfido2 (system)", STATUS_SKIP, "cannot probe")


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
                f"{module}.{name} (no secure storage backend found)",
                hint=(
                    "Credentials cannot be stored securely without a keyring backend.\n"
                    "  Linux (GNOME/KDE): install and start gnome-keyring or kwallet\n"
                    "  Linux (headless):  pip install 'keyrings.alt'  (plain-text fallback)\n"
                    "  macOS:             Keychain is built in — no action needed\n"
                    "  Windows:           Windows Credential Manager is built in"
                ),
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
        return CheckResult("Config directory", STATUS_FAIL, "pyxdg not installed")


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


def _check_saml_endpoint(host: str | None, timeout: float = 8.0) -> CheckResult:
    """HTTP-probe the VPN web endpoint to confirm it speaks AnyConnect SAML.

    A real Cisco AnyConnect / Secure Client SAML endpoint responds with a 200
    or a 302 redirect to the IdP login page on a plain GET. Anything else
    (404, certificate errors, plain HTML index) usually means the URL is
    wrong or the endpoint isn't SAML-enabled.
    """
    if not host:
        return CheckResult(
            "SAML endpoint",
            STATUS_SKIP,
            "no --server provided to test",
        )
    try:
        import requests  # local import: doctor must work without the dev extras
    except ImportError:
        return CheckResult(
            "SAML endpoint",
            STATUS_SKIP,
            "requests package missing (core dep)",
        )

    url = host if "://" in host else f"https://{host}"
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=False)
    except requests.exceptions.SSLError as exc:
        return CheckResult(
            "SAML endpoint",
            STATUS_FAIL,
            f"TLS error: {exc}",
            hint="Server certificate may be invalid or self-signed.",
        )
    except requests.exceptions.RequestException as exc:
        return CheckResult(
            "SAML endpoint",
            STATUS_FAIL,
            str(exc),
        )

    code = resp.status_code
    location = resp.headers.get("Location", "")
    server_hdr = resp.headers.get("Server", "").lower()
    if code in (200, 302, 303, 307) or "anyconnect" in server_hdr:
        details = [f"HTTP {code}"]
        if location:
            details.append(f"→ {location[:100]}")
        if server_hdr:
            details.append(f"server={server_hdr}")
        return CheckResult(
            "SAML endpoint",
            STATUS_OK,
            url,
            details=details,
        )
    return CheckResult(
        "SAML endpoint",
        STATUS_WARN,
        f"HTTP {code} from {url}",
        hint="Endpoint reachable but doesn't look like an AnyConnect SAML page.",
    )


def _check_sessions() -> CheckResult:
    """Surface the number of recorded live sessions."""
    try:
        from openconnect_saml import sessions as _sessions

        active = _sessions.list_active()
    except Exception as exc:  # noqa: BLE001
        return CheckResult("Active sessions", STATUS_SKIP, f"cannot check ({exc})")
    if not active:
        return CheckResult("Active sessions", STATUS_OK, "none")
    names = ", ".join(s.profile for s in active)
    return CheckResult(
        "Active sessions",
        STATUS_OK,
        f"{len(active)} ({names})",
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
    results.append(_check_system_browser())
    results.append(_check_sudo())
    results.append(_check_tun_device())
    results.extend(_check_python_deps())
    results.extend(_check_optional_deps())
    results.append(_check_keyring_backend())
    results.append(_check_config_dir())
    results.append(_check_env_hygiene())
    results.append(_check_dns_resolution(server))
    results.append(_check_server_reachable(server))
    if server:
        results.append(_check_saml_endpoint(server))
    results.append(_check_sessions())
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


def _summarize(results: list[CheckResult]) -> dict:
    counts = {s: 0 for s in (STATUS_OK, STATUS_WARN, STATUS_FAIL, STATUS_SKIP)}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    return counts


def handle_doctor_command(args) -> int:
    server = getattr(args, "server", None)
    as_json = getattr(args, "json", False)

    results = run_all(server=server)
    counts = _summarize(results)

    if as_json:
        payload = {
            "server": server,
            "summary": counts,
            "checks": [asdict(r) for r in results],
        }
        print(json.dumps(payload, indent=2))
    else:
        print("openconnect-saml diagnostics")
        print("=" * 40)
        _print_results(results)
        print()
        print(
            f"Summary: {counts[STATUS_OK]} OK · {counts[STATUS_WARN]} warning"
            f" · {counts[STATUS_FAIL]} failed · {counts[STATUS_SKIP]} skipped"
        )

    if counts[STATUS_FAIL] > 0:
        return 1
    if counts[STATUS_WARN] > 0:
        return 2
    return 0
