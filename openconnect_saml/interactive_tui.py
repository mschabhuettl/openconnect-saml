"""Interactive Terminal UI for openconnect-saml.

A `rich`-based full-screen TUI that lets the user browse profiles,
connect / disconnect, see live status, and inspect history without
leaving the terminal. Started via ``openconnect-saml tui``.

Requires the ``[tui]`` extra (`rich`). For monitoring-only usage use
``openconnect-saml status`` or ``status --watch --json`` instead.
"""

from __future__ import annotations

import os
import select
import subprocess  # nosec
import sys
import termios
import time
import tty

from openconnect_saml import config, history
from openconnect_saml.tui import _augment_with_rate, _collect_status, _format_bytes, _format_rate


def _has_rich() -> bool:
    try:
        import rich  # noqa: F401

        return True
    except ImportError:
        return False


def _install_hint(package: str) -> str:
    """Render a distro-aware installation hint for an optional dep.

    Maps the upstream PyPI package name to the corresponding distro
    package and points the user at the right install command. The
    pip variant always works as a fallback.
    """
    pip_map = {"rich": "openconnect-saml[tui]"}
    distro_map = {
        "arch": {"rich": "python-rich"},
        "debian": {"rich": "python3-rich"},
        "fedora": {"rich": "python3-rich"},
    }

    pip_pkg = pip_map.get(package, package)
    lines = [f"  pip install '{pip_pkg}'"]
    distro = _detect_distro()
    if distro and package in distro_map.get(distro, {}):
        sys_pkg = distro_map[distro][package]
        if distro == "arch":
            lines.insert(0, f"  sudo pacman -S {sys_pkg}")
        elif distro == "debian":
            lines.insert(0, f"  sudo apt install {sys_pkg}")
        elif distro == "fedora":
            lines.insert(0, f"  sudo dnf install {sys_pkg}")
    return "Install with one of:\n" + "\n".join(lines)


def _detect_distro() -> str | None:
    """Return ``arch`` / ``debian`` / ``fedora`` or None on best-effort basis."""
    import os as _os

    if _os.path.exists("/etc/arch-release"):
        return "arch"
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("ID="):
                    val = line.split("=", 1)[1].strip().strip('"').lower()
                    if val in ("arch", "manjaro", "endeavouros", "cachyos"):
                        return "arch"
                    if val in ("debian", "ubuntu", "linuxmint", "pop"):
                        return "debian"
                    if val in ("fedora", "rhel", "centos", "rocky", "almalinux"):
                        return "fedora"
    except OSError:
        pass
    return None


def _read_key(timeout: float = 0.5) -> str | None:
    """Non-blocking single-key read from stdin, or None on timeout.

    Returns one of: 'q', 'c', 'd', 'r', 'h', 'p', 's', 'UP', 'DOWN',
    'ENTER', or any other single character. Escape sequences (arrows)
    are decoded to 'UP'/'DOWN'/'LEFT'/'RIGHT'.
    """
    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    rlist, _, _ = select.select([fd], [], [], timeout)
    if not rlist:
        return None
    ch = os.read(fd, 1).decode(errors="replace")
    if ch != "\x1b":
        if ch == "\r" or ch == "\n":
            return "ENTER"
        return ch
    # Escape sequence — read up to two more bytes for arrow keys
    rlist2, _, _ = select.select([fd], [], [], 0.05)
    if not rlist2:
        return "ESC"
    seq = os.read(fd, 2).decode(errors="replace")
    return {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT"}.get(seq, "ESC")


class InteractiveTUI:
    """Full-screen, keyboard-driven TUI."""

    HELP = (
        "↑/↓ select profile · [c]onnect · [d]isconnect · [r]efresh · [h]istory · [s]tatus · [q]uit"
    )

    def __init__(self):
        self.cfg = config.load()
        self.profiles = sorted(dict(self.cfg.list_profiles()))
        self.cursor = 0 if self.profiles else -1
        self.proc: subprocess.Popen | None = None
        self.message: str = ""
        self.message_until: float = 0
        self.view: str = "main"  # main | history
        self._prev_status: dict | None = None

    # ---------------------------------------------------------- helpers

    def _flash(self, msg: str, seconds: float = 3.0) -> None:
        self.message = msg
        self.message_until = time.monotonic() + seconds

    def _selected_profile(self) -> str | None:
        if not self.profiles or self.cursor < 0:
            return None
        return self.profiles[self.cursor]

    def _refresh_profiles(self) -> None:
        self.cfg = config.load()
        self.profiles = sorted(dict(self.cfg.list_profiles()))
        if self.cursor >= len(self.profiles):
            self.cursor = max(0, len(self.profiles) - 1)
        self._flash("Profiles refreshed.")

    def _connect(self) -> None:
        name = self._selected_profile()
        if not name:
            self._flash("No profile selected.")
            return
        if self.proc and self.proc.poll() is None:
            self._flash("Already connecting / connected — disconnect first.")
            return
        cmd = [sys.executable, "-m", "openconnect_saml.cli", "connect", name]
        self.proc = subprocess.Popen(  # nosec
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._flash(f"Connecting to '{name}'…")

    def _disconnect(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._flash("Disconnect signal sent.")
        else:
            self._flash("No active connection.")

    # -------------------------------------------------------------- ui

    def _render(self, console) -> None:
        from rich.layout import Layout
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=2),
        )

        # Header
        title = Text("openconnect-saml — interactive TUI", style="bold cyan")
        layout["header"].update(Panel(title, border_style="cyan"))

        # Left: profile list
        prof_table = Table(show_header=True, expand=True, header_style="bold")
        prof_table.add_column(" ", width=2)
        prof_table.add_column("Name")
        prof_table.add_column("Server", overflow="fold")
        if not self.profiles:
            prof_table.add_row("", "[dim]no profiles yet[/]", "[dim]openconnect-saml setup[/]")
        for i, name in enumerate(self.profiles):
            prof = self.cfg.profiles.get(name)
            server = getattr(prof, "server", "?")
            cursor = "›" if i == self.cursor else " "
            row_style = "reverse" if i == self.cursor else ""
            prof_table.add_row(cursor, name, server, style=row_style)
        layout["left"].update(Panel(prof_table, title="Profiles", border_style="blue"))

        # Right: status or history depending on view
        if self.view == "history":
            entries = list(reversed(history.read_history(limit=20)))
            hist_table = Table(show_header=True, expand=True, header_style="bold")
            hist_table.add_column("When", width=16)
            hist_table.add_column("Event", width=12)
            hist_table.add_column("Profile", width=14)
            hist_table.add_column("Server", overflow="fold")
            for e in entries:
                hist_table.add_row(
                    str(e.get("timestamp", ""))[:16],
                    str(e.get("event", "?")),
                    str(e.get("profile") or "-"),
                    str(e.get("server", "?")),
                )
            layout["right"].update(
                Panel(hist_table, title="History (last 20)", border_style="green")
            )
        else:
            status = _collect_status()
            if status is not None:
                status["_sampled_at"] = time.monotonic()
                _augment_with_rate(status, self._prev_status)
            self._prev_status = status

            stat_table = Table(show_header=False, expand=True)
            stat_table.add_column("Key", style="bold cyan", min_width=14)
            stat_table.add_column("Value")
            if not status:
                stat_table.add_row("State", "[red]Disconnected[/]")
                if self.proc and self.proc.poll() is None:
                    stat_table.add_row("Process", f"PID {self.proc.pid} (connecting…)")
            else:
                stat_table.add_row("State", "[green]Connected[/]")
                stat_table.add_row("Profile", str(status.get("profile", "?")))
                stat_table.add_row("Server", str(status.get("server", "?")))
                stat_table.add_row("User", str(status.get("user", "?")))
                stat_table.add_row("IP", str(status.get("ip", "?")))
                stat_table.add_row("Uptime", str(status.get("uptime") or "?"))
                tx = _format_bytes(status.get("tx"))
                rx = _format_bytes(status.get("rx"))
                stat_table.add_row("TX / RX", f"{tx} / {rx}")
                if status.get("tx_rate") is not None or status.get("rx_rate") is not None:
                    stat_table.add_row(
                        "Rate ↑/↓",
                        f"{_format_rate(status.get('tx_rate'))}"
                        f" / {_format_rate(status.get('rx_rate'))}",
                    )
            layout["right"].update(Panel(stat_table, title="Status (live)", border_style="green"))

        # Footer
        msg = ""
        if self.message and time.monotonic() < self.message_until:
            msg = f"  [yellow]{self.message}[/]"
        layout["footer"].update(Panel(Text.from_markup(self.HELP + msg), border_style="dim"))

        console.print(layout)

    # ------------------------------------------------------------ main

    def run(self) -> int:
        if not _has_rich():
            print(
                "Error: `rich` is required for the interactive TUI.",
                file=sys.stderr,
            )
            for line in _install_hint("rich").splitlines():
                print(line, file=sys.stderr)
            return 1
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            print("Error: TUI needs an interactive terminal.", file=sys.stderr)
            return 1

        from rich.console import Console
        from rich.live import Live

        console = Console()
        old_settings = termios.tcgetattr(sys.stdin.fileno())
        try:
            tty.setcbreak(sys.stdin.fileno())
            with Live(console=console, screen=True, refresh_per_second=4) as live:
                while True:
                    self._render(console)
                    # Live captures via the latest console.print; trigger refresh
                    live.refresh()
                    key = _read_key(timeout=0.5)
                    if key is None:
                        continue
                    if key in ("q", "Q", "ESC"):
                        return 0
                    if key in ("UP", "k"):
                        if self.cursor > 0:
                            self.cursor -= 1
                    elif key in ("DOWN", "j"):
                        if self.cursor < len(self.profiles) - 1:
                            self.cursor += 1
                    elif key in ("c", "ENTER"):
                        self._connect()
                    elif key == "d":
                        self._disconnect()
                    elif key == "r":
                        self._refresh_profiles()
                    elif key == "h":
                        self.view = "history"
                    elif key == "s":
                        self.view = "main"
        finally:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
            if self.proc and self.proc.poll() is None:
                # Don't kill the running VPN on quit; just detach.
                pass


def handle_tui_command(args=None) -> int:
    """Entry-point for ``openconnect-saml tui``."""
    return InteractiveTUI().run()
