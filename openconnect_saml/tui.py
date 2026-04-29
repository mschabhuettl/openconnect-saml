"""Connection status TUI for openconnect-saml.

Shows live VPN connection status including profile, server, IP, uptime,
and traffic statistics. Requires optional 'rich' dependency.

Install: pip install openconnect-saml[tui]
"""

import json
import re
import subprocess  # nosec
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openconnect_saml import config


def _find_vpn_process():
    """Find running openconnect process and return (pid, cmdline) or None."""
    try:
        result = subprocess.run(  # nosec
            ["pgrep", "-a", "openconnect"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().split("\n")
            for line in lines:
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    pid = int(parts[0])
                    cmdline = parts[1]
                    return pid, cmdline
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def _get_process_start_time(pid):
    """Get process start time from /proc/<pid>/stat."""
    try:
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists():
            # Use creation time of /proc/<pid> directory
            proc_dir = Path(f"/proc/{pid}")
            create_time = proc_dir.stat().st_ctime
            return datetime.fromtimestamp(create_time, tz=timezone.utc)
    except (OSError, ValueError):
        pass
    return None


def _format_duration(seconds):
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}m {s}s"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}h {m:02d}m"


def _get_vpn_interface():
    """Find the VPN tunnel interface (tun*, utun*)."""
    try:
        result = subprocess.run(  # nosec
            ["ip", "-o", "link", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                match = re.search(r"\d+:\s+(tun\d+|utun\d+)", line)
                if match:
                    return match.group(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_interface_ip(iface):
    """Get IP address of an interface."""
    try:
        result = subprocess.run(  # nosec
            ["ip", "-4", "addr", "show", iface],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
            if match:
                return match.group(1)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_traffic_stats(iface):
    """Read TX/RX bytes from /proc/net/dev."""
    try:
        proc_net = Path("/proc/net/dev")
        if proc_net.exists():
            content = proc_net.read_text()
            for line in content.split("\n"):
                if iface + ":" in line:
                    parts = line.split(":")
                    if len(parts) >= 2:
                        values = parts[1].split()
                        if len(values) >= 9:
                            rx_bytes = int(values[0])
                            tx_bytes = int(values[8])
                            return tx_bytes, rx_bytes
    except (OSError, ValueError, IndexError):
        pass
    return None, None


def _format_bytes(b):
    """Format bytes into human-readable form."""
    if b is None:
        return "N/A"
    if b < 1024:
        return f"{b} B"
    elif b < 1024 * 1024:
        return f"{b / 1024:.1f} KB"
    elif b < 1024 * 1024 * 1024:
        return f"{b / (1024 * 1024):.1f} MB"
    else:
        return f"{b / (1024 * 1024 * 1024):.2f} GB"


def _extract_server_from_cmdline(cmdline):
    """Extract server URL from openconnect command line."""
    parts = cmdline.split()
    # The server is usually the last argument
    for part in reversed(parts):
        if not part.startswith("-") and ("." in part or ":" in part):
            # Remove https:// prefix for display
            server = part.replace("https://", "").replace("http://", "")
            return server
    return "unknown"


def _get_reconnect_count():
    """Estimate reconnect count (not reliable without state file)."""
    return 0


def _collect_status():
    """Collect all VPN status information."""
    proc = _find_vpn_process()
    if not proc:
        return None

    pid, cmdline = proc
    iface = _get_vpn_interface()

    status = {
        "connected": True,
        "pid": pid,
        "server": _extract_server_from_cmdline(cmdline),
        "interface": iface or "N/A",
        "ip": _get_interface_ip(iface) if iface else "N/A",
        "uptime": None,
        "tx": None,
        "rx": None,
        "reconnects": _get_reconnect_count(),
    }

    start_time = _get_process_start_time(pid)
    if start_time:
        elapsed = (datetime.now(tz=timezone.utc) - start_time).total_seconds()
        status["uptime"] = _format_duration(elapsed)

    if iface:
        tx, rx = _get_traffic_stats(iface)
        status["tx"] = tx
        status["rx"] = rx

    # Try to get profile info from config
    cfg = config.load()
    status["profile"] = cfg.active_profile or "default"
    if cfg.credentials:
        status["user"] = cfg.credentials.username
    else:
        status["user"] = "N/A"

    return status


def _print_status_plain(status):
    """Print status without rich (fallback)."""
    if not status:
        print("❌ openconnect-saml — Disconnected")
        print("No active VPN connection found.")
        return

    print("🔐 openconnect-saml — Connected")
    print()
    print(f"  Profile:      {status['profile']}")
    print(f"  Server:       {status['server']}")
    print(f"  User:         {status['user']}")
    print(f"  Connected:    {status['uptime'] or 'N/A'}")
    print(f"  IP Address:   {status['ip']}")
    tx_str = _format_bytes(status["tx"])
    rx_str = _format_bytes(status["rx"])
    print(f"  TX / RX:      {tx_str} / {rx_str}")
    print(f"  Reconnects:   {status['reconnects']}")


def _print_status_rich(status):
    """Print status using rich library."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        _print_status_plain(status)
        return

    console = Console()

    if not status:
        console.print("[bold red]❌ openconnect-saml — Disconnected[/]")
        console.print("No active VPN connection found.")
        return

    console.print("[bold green]🔐 openconnect-saml — Connected[/]")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="bold cyan", min_width=14)
    table.add_column("Value")

    tx_str = _format_bytes(status["tx"])
    rx_str = _format_bytes(status["rx"])

    table.add_row("Profile", status["profile"])
    table.add_row("Server", status["server"])
    table.add_row("User", status["user"])
    table.add_row("Connected", status["uptime"] or "N/A")
    table.add_row("IP Address", status["ip"])
    table.add_row("TX / RX", f"{tx_str} / {rx_str}")
    table.add_row("Reconnects", str(status["reconnects"]))

    console.print(table)


def _print_status_json(status):
    """Print status as a single JSON object on stdout."""
    payload = {"connected": False} if status is None else dict(status)
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def handle_status_command(args):
    """Handle the 'status' subcommand."""
    watch = getattr(args, "watch", False)
    as_json = getattr(args, "json", False)

    def _render(status):
        if as_json:
            _print_status_json(status)
            return
        try:
            _print_status_rich(status)
        except Exception:
            _print_status_plain(status)

    if watch:
        try:
            while True:
                if not as_json:
                    # Clear screen using ANSI escape (avoids shell injection via os.system)
                    print("\033[2J\033[H", end="", flush=True)
                _render(_collect_status())
                time.sleep(2)
        except KeyboardInterrupt:
            return 0
    else:
        status = _collect_status()
        _render(status)
        return 0 if status else 1
