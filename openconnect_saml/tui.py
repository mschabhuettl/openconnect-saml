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


def _format_rate(bps):
    """Format bytes/sec as a human-readable rate string."""
    if bps is None:
        return "—"
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 * 1024:
        return f"{bps / 1024:.1f} KB/s"
    if bps < 1024 * 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    return f"{bps / (1024 * 1024 * 1024):.2f} GB/s"


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


def _collect_status_for_pid(pid: int, cmdline: str, profile: str = "", user: str = ""):
    """Build a status dict for a single openconnect pid."""
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
        "profile": profile or "default",
        "user": user or "N/A",
    }

    start_time = _get_process_start_time(pid)
    if start_time:
        elapsed = (datetime.now(tz=timezone.utc) - start_time).total_seconds()
        status["uptime"] = _format_duration(elapsed)

    if iface:
        tx, rx = _get_traffic_stats(iface)
        status["tx"] = tx
        status["rx"] = rx

    return status


def _collect_status():
    """Collect VPN status for the most recent active session.

    Backwards-compatible: returns the same shape as before but now
    prefers a recorded session (multi-session aware) over `pgrep`. Falls
    back to `pgrep` if no session record matches a live process.
    """
    from openconnect_saml import sessions as _sessions

    active = _sessions.list_active()
    cfg = config.load()

    if active:
        # Pick the active session whose profile matches the config's
        # active_profile, if any; otherwise the first.
        sess = next((s for s in active if s.profile == cfg.active_profile), active[0])
        cmdline = ""
        proc = _find_vpn_process()
        if proc and proc[0] == sess.pid:
            cmdline = proc[1]
        return _collect_status_for_pid(
            sess.pid, cmdline or sess.server, profile=sess.profile, user=sess.user
        )

    proc = _find_vpn_process()
    if not proc:
        return None
    pid, cmdline = proc
    return _collect_status_for_pid(
        pid,
        cmdline,
        profile=cfg.active_profile or "default",
        user=cfg.credentials.username if cfg.credentials else "",
    )


def _collect_all_statuses():
    """Return one status dict per active recorded session."""
    from openconnect_saml import sessions as _sessions

    out: list[dict] = []
    proc = _find_vpn_process()
    pid_to_cmdline: dict[int, str] = {}
    if proc:
        pid_to_cmdline[proc[0]] = proc[1]
    for sess in _sessions.list_active():
        cmdline = pid_to_cmdline.get(sess.pid, sess.server)
        out.append(_collect_status_for_pid(sess.pid, cmdline, profile=sess.profile, user=sess.user))
    return out


def _plain_output() -> bool:
    """Honor NO_COLOR / non-TTY output for the plain status renderer."""
    import os

    if os.environ.get("NO_COLOR") is not None:
        return True
    return not sys.stdout.isatty()


def _print_status_plain(status):
    """Print status without rich (fallback)."""
    plain = _plain_output()
    disconnected_glyph = "[Disconnected]" if plain else "❌ openconnect-saml — Disconnected"
    connected_glyph = "[Connected]" if plain else "🔐 openconnect-saml — Connected"
    if not status:
        print(disconnected_glyph)
        print("No active VPN connection found.")
        return

    print(connected_glyph)
    print()
    print(f"  Profile:      {status['profile']}")
    print(f"  Server:       {status['server']}")
    print(f"  User:         {status['user']}")
    print(f"  Connected:    {status['uptime'] or 'N/A'}")
    print(f"  IP Address:   {status['ip']}")
    tx_str = _format_bytes(status["tx"])
    rx_str = _format_bytes(status["rx"])
    print(f"  TX / RX:      {tx_str} / {rx_str}")
    if status.get("tx_rate") is not None or status.get("rx_rate") is not None:
        tx_rate = _format_rate(status.get("tx_rate"))
        rx_rate = _format_rate(status.get("rx_rate"))
        print(f"  Rate (↑/↓):   {tx_rate} / {rx_rate}")
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
    if status.get("tx_rate") is not None or status.get("rx_rate") is not None:
        rate_str = f"{_format_rate(status.get('tx_rate'))} / {_format_rate(status.get('rx_rate'))}"
        table.add_row("Rate (↑/↓)", rate_str)
    table.add_row("Reconnects", str(status["reconnects"]))

    console.print(table)


def _print_status_json(status):
    """Print status as a single JSON object on stdout."""
    payload = {"connected": False} if status is None else dict(status)
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _augment_with_rate(status, prev):
    """Annotate ``status`` with tx_rate / rx_rate (bytes/sec) using ``prev`` as baseline."""
    if not status or not prev:
        return status
    if not status.get("interface") or status["interface"] != prev.get("interface"):
        return status
    dt = (status.get("_sampled_at") or 0) - (prev.get("_sampled_at") or 0)
    if dt <= 0:
        return status
    for key in ("tx", "rx"):
        cur = status.get(key)
        old = prev.get(key)
        if cur is not None and old is not None and cur >= old:
            status[f"{key}_rate"] = (cur - old) / dt
    return status


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

    def _sample():
        s = _collect_status()
        if s is not None:
            s["_sampled_at"] = time.monotonic()
        return s

    if watch:
        prev = None
        try:
            while True:
                if not as_json:
                    # Clear screen using ANSI escape (avoids shell injection via os.system)
                    print("\033[2J\033[H", end="", flush=True)
                status = _sample()
                _augment_with_rate(status, prev)
                _render(status)
                prev = status
                time.sleep(2)
        except KeyboardInterrupt:
            return 0
    else:
        status = _sample()
        _render(status)
        return 0 if status else 1
