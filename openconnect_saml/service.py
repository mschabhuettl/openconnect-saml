"""Systemd service management for openconnect-saml.

Provides install/uninstall/start/stop/status/logs subcommands to manage
a systemd unit that keeps the VPN connection alive with auto-reconnect.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess  # nosec
import sys
import textwrap
from pathlib import Path

import structlog

logger = structlog.get_logger()

UNIT_DIR = Path("/etc/systemd/system")
USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
UNIT_PREFIX = "openconnect-saml"


def _unit_dir(user_mode: bool) -> Path:
    return USER_UNIT_DIR if user_mode else UNIT_DIR


def _systemctl_args(user_mode: bool) -> list[str]:
    """Prefix arguments for systemctl: ``["systemctl"]`` or ``["systemctl", "--user"]``."""
    return ["systemctl", "--user"] if user_mode else ["systemctl"]


def _unit_name(server: str) -> str:
    """Derive a systemd unit name from the server address."""
    # Sanitize server name for use in unit file names
    safe = server.replace("https://", "").replace("http://", "")
    safe = safe.replace("/", "-").replace(":", "-").strip("-")
    return f"{UNIT_PREFIX}@{safe}.service"


def _find_executable() -> str:
    """Find the openconnect-saml executable."""
    which = shutil.which("openconnect-saml")
    if which:
        return which
    # Fallback: try the current Python's entry point
    return f"{sys.executable} -m openconnect_saml.cli"


def generate_unit(
    server: str,
    user: str | None = None,
    extra_args: str = "",
    browser: str = "headless",
    max_retries: int | None = None,
    user_mode: bool = False,
) -> str:
    """Generate a systemd unit file for the given server.

    Parameters
    ----------
    server : str
        VPN server address.
    user : str or None
        Username for authentication.
    extra_args : str
        Additional CLI arguments.
    browser : str
        Browser backend to use (headless, chrome, qt).
    max_retries : int or None
        Max reconnection retries (None = unlimited).
    """
    executable = _find_executable()

    cmd_parts = [executable, "--server", shlex.quote(server)]

    if browser == "headless":
        cmd_parts.append("--headless")
    else:
        cmd_parts.extend(["--browser", browser])

    if user:
        cmd_parts.extend(["--user", shlex.quote(user)])

    cmd_parts.append("--reconnect")

    if max_retries is not None:
        cmd_parts.extend(["--max-retries", str(max_retries)])

    if extra_args:
        cmd_parts.append(extra_args)

    exec_start = " ".join(cmd_parts)

    install_target = "default.target" if user_mode else "multi-user.target"
    unit = textwrap.dedent(f"""\
        [Unit]
        Description=OpenConnect SAML VPN ({server})
        After=network-online.target
        Wants=network-online.target

        [Service]
        Type=simple
        ExecStart={exec_start}
        Restart=on-failure
        RestartSec=30
        WatchdogSec=300
        Environment=HOME={Path.home()}

        [Install]
        WantedBy={install_target}
    """)
    return unit


def install(
    server: str,
    user: str | None = None,
    extra_args: str = "",
    browser: str = "headless",
    max_retries: int | None = None,
    user_mode: bool = False,
) -> int:
    """Install a systemd unit for the given server.

    When ``user_mode`` is True the unit goes under
    ``~/.config/systemd/user/`` and is managed via ``systemctl --user`` —
    no sudo needed, but the service stops on logout (use
    ``loginctl enable-linger`` to keep it running across sessions).
    """
    unit_name = _unit_name(server)
    unit_dir = _unit_dir(user_mode)
    unit_path = unit_dir / unit_name

    if user_mode:
        unit_dir.mkdir(parents=True, exist_ok=True)

    unit_content = generate_unit(
        server,
        user=user,
        extra_args=extra_args,
        browser=browser,
        max_retries=max_retries,
        user_mode=user_mode,
    )

    logger.info("Installing systemd unit", unit=unit_name, path=str(unit_path), user_mode=user_mode)

    try:
        unit_path.write_text(unit_content)
        unit_path.chmod(0o644)
    except PermissionError:
        if user_mode:
            logger.error("Permission denied", path=str(unit_path))
        else:
            logger.error(
                "Permission denied. Run with sudo, or use 'service install --user' for "
                "a per-user unit (no sudo required).",
                path=str(unit_path),
            )
        return 1

    sysctl = _systemctl_args(user_mode)
    subprocess.run([*sysctl, "daemon-reload"], check=True)  # nosec
    logger.info("Systemd unit installed", unit=unit_name)

    subprocess.run([*sysctl, "enable", unit_name], check=True)  # nosec
    logger.info("Systemd unit enabled", unit=unit_name)

    print(f"✓ Unit installed: {unit_path}")
    if user_mode:
        print(f"  Start with: openconnect-saml service start --server {server} --user")
        print("  Tip: 'loginctl enable-linger' keeps user services running across logouts.")
    else:
        print(f"  Start with: openconnect-saml service start --server {server}")
    return 0


def _resolve_unit_mode(server: str, user_mode: bool) -> bool:
    """Pick user_mode automatically when False but only the user-mode unit
    file exists (a usability win — users don't have to type --user twice)."""
    if user_mode:
        return True
    if (UNIT_DIR / _unit_name(server)).exists():
        return False
    return (USER_UNIT_DIR / _unit_name(server)).exists()


def uninstall(server: str, user_mode: bool = False) -> int:
    """Uninstall the systemd unit for the given server."""
    user_mode = _resolve_unit_mode(server, user_mode)
    unit_name = _unit_name(server)
    unit_path = _unit_dir(user_mode) / unit_name

    if not unit_path.exists():
        logger.error("Unit file not found", path=str(unit_path))
        return 1

    logger.info("Uninstalling systemd unit", unit=unit_name, user_mode=user_mode)

    sysctl = _systemctl_args(user_mode)
    subprocess.run([*sysctl, "stop", unit_name], check=False)  # nosec
    subprocess.run([*sysctl, "disable", unit_name], check=False)  # nosec

    try:
        unit_path.unlink()
    except PermissionError:
        logger.error("Permission denied. Run with sudo or as root.")
        return 1

    subprocess.run([*sysctl, "daemon-reload"], check=True)  # nosec
    logger.info("Systemd unit removed", unit=unit_name)
    print(f"✓ Unit removed: {unit_path}")
    return 0


def start(server: str, user_mode: bool = False) -> int:
    """Start the systemd unit for the given server."""
    user_mode = _resolve_unit_mode(server, user_mode)
    unit_name = _unit_name(server)
    result = subprocess.run([*_systemctl_args(user_mode), "start", unit_name])  # nosec
    if result.returncode == 0:
        print(f"✓ Started {unit_name}")
    else:
        print(f"✗ Failed to start {unit_name}")
    return result.returncode


def stop(server: str, user_mode: bool = False) -> int:
    """Stop the systemd unit for the given server."""
    user_mode = _resolve_unit_mode(server, user_mode)
    unit_name = _unit_name(server)
    result = subprocess.run([*_systemctl_args(user_mode), "stop", unit_name])  # nosec
    if result.returncode == 0:
        print(f"✓ Stopped {unit_name}")
    else:
        print(f"✗ Failed to stop {unit_name}")
    return result.returncode


def status(server: str | None = None, user_mode: bool = False) -> int:
    """Show status of the systemd unit(s)."""
    if server:
        user_mode = _resolve_unit_mode(server, user_mode)
        unit_name = _unit_name(server)
        return subprocess.run([*_systemctl_args(user_mode), "status", unit_name]).returncode  # nosec

    # Show all openconnect-saml units
    result = subprocess.run(  # nosec
        ["systemctl", "list-units", f"{UNIT_PREFIX}@*", "--no-pager"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout)
    else:
        print("No openconnect-saml service units found.")
    return 0


def logs(server: str | None = None, follow: bool = False, user_mode: bool = False) -> int:
    """Show logs for the systemd unit(s)."""
    if server:
        user_mode = _resolve_unit_mode(server, user_mode)
    cmd = ["journalctl", "--no-pager", "-n", "100"]
    if user_mode:
        cmd.append("--user")
    if server:
        unit_name = _unit_name(server)
        cmd.extend(["-u", unit_name])
    else:
        cmd.extend(["-u", f"{UNIT_PREFIX}@*"])
    if follow:
        cmd.append("-f")
    return subprocess.run(cmd).returncode  # nosec


def handle_service_command(args) -> int:
    """Dispatch service subcommand."""
    action = args.service_action
    user_mode = bool(getattr(args, "user_mode", False))

    if action == "install":
        if not args.server:
            print("Error: --server is required for install")
            return 1
        return install(
            server=args.server,
            user=getattr(args, "user", None),
            browser=getattr(args, "browser", "headless"),
            max_retries=getattr(args, "max_retries", None),
            user_mode=user_mode,
        )
    elif action == "uninstall":
        if not args.server:
            print("Error: --server is required for uninstall")
            return 1
        return uninstall(args.server, user_mode=user_mode)
    elif action == "start":
        if not args.server:
            print("Error: --server is required for start")
            return 1
        return start(args.server, user_mode=user_mode)
    elif action == "stop":
        if not args.server:
            print("Error: --server is required for stop")
            return 1
        return stop(args.server, user_mode=user_mode)
    elif action == "status":
        return status(getattr(args, "server", None), user_mode=user_mode)
    elif action == "logs":
        return logs(
            server=getattr(args, "server", None),
            follow=getattr(args, "follow", False),
            user_mode=user_mode,
        )
    else:
        print(f"Unknown service action: {action}")
        return 1
