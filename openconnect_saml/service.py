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
UNIT_PREFIX = "openconnect-saml"


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
        WantedBy=multi-user.target
    """)
    return unit


def install(
    server: str,
    user: str | None = None,
    extra_args: str = "",
    browser: str = "headless",
    max_retries: int | None = None,
) -> int:
    """Install a systemd unit for the given server."""
    unit_name = _unit_name(server)
    unit_path = UNIT_DIR / unit_name

    unit_content = generate_unit(
        server, user=user, extra_args=extra_args, browser=browser, max_retries=max_retries
    )

    logger.info("Installing systemd unit", unit=unit_name, path=str(unit_path))

    try:
        unit_path.write_text(unit_content)
        unit_path.chmod(0o644)
    except PermissionError:
        logger.error(
            "Permission denied. Run with sudo or as root.",
            path=str(unit_path),
        )
        return 1

    # Reload systemd
    subprocess.run(["systemctl", "daemon-reload"], check=True)  # nosec
    logger.info("Systemd unit installed", unit=unit_name)

    # Enable the unit
    subprocess.run(["systemctl", "enable", unit_name], check=True)  # nosec
    logger.info("Systemd unit enabled", unit=unit_name)

    print(f"✓ Unit installed: {unit_path}")
    print(f"  Start with: openconnect-saml service start --server {server}")
    return 0


def uninstall(server: str) -> int:
    """Uninstall the systemd unit for the given server."""
    unit_name = _unit_name(server)
    unit_path = UNIT_DIR / unit_name

    if not unit_path.exists():
        logger.error("Unit file not found", path=str(unit_path))
        return 1

    logger.info("Uninstalling systemd unit", unit=unit_name)

    # Stop and disable first
    subprocess.run(["systemctl", "stop", unit_name], check=False)  # nosec
    subprocess.run(["systemctl", "disable", unit_name], check=False)  # nosec

    try:
        unit_path.unlink()
    except PermissionError:
        logger.error("Permission denied. Run with sudo or as root.")
        return 1

    subprocess.run(["systemctl", "daemon-reload"], check=True)  # nosec
    logger.info("Systemd unit removed", unit=unit_name)
    print(f"✓ Unit removed: {unit_path}")
    return 0


def start(server: str) -> int:
    """Start the systemd unit for the given server."""
    unit_name = _unit_name(server)
    result = subprocess.run(["systemctl", "start", unit_name])  # nosec
    if result.returncode == 0:
        print(f"✓ Started {unit_name}")
    else:
        print(f"✗ Failed to start {unit_name}")
    return result.returncode


def stop(server: str) -> int:
    """Stop the systemd unit for the given server."""
    unit_name = _unit_name(server)
    result = subprocess.run(["systemctl", "stop", unit_name])  # nosec
    if result.returncode == 0:
        print(f"✓ Stopped {unit_name}")
    else:
        print(f"✗ Failed to stop {unit_name}")
    return result.returncode


def status(server: str | None = None) -> int:
    """Show status of the systemd unit(s)."""
    if server:
        unit_name = _unit_name(server)
        return subprocess.run(["systemctl", "status", unit_name]).returncode  # nosec

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


def logs(server: str | None = None, follow: bool = False) -> int:
    """Show logs for the systemd unit(s)."""
    cmd = ["journalctl", "--no-pager", "-n", "100"]
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

    if action == "install":
        if not args.server:
            print("Error: --server is required for install")
            return 1
        return install(
            server=args.server,
            user=getattr(args, "user", None),
            browser=getattr(args, "browser", "headless"),
            max_retries=getattr(args, "max_retries", None),
        )
    elif action == "uninstall":
        if not args.server:
            print("Error: --server is required for uninstall")
            return 1
        return uninstall(args.server)
    elif action == "start":
        if not args.server:
            print("Error: --server is required for start")
            return 1
        return start(args.server)
    elif action == "stop":
        if not args.server:
            print("Error: --server is required for stop")
            return 1
        return stop(args.server)
    elif action == "status":
        return status(getattr(args, "server", None))
    elif action == "logs":
        return logs(
            server=getattr(args, "server", None),
            follow=getattr(args, "follow", False),
        )
    else:
        print(f"Unknown service action: {action}")
        return 1
