"""Connection history — a lightweight audit log of VPN sessions.

Stores records of connect / disconnect / error events as JSON lines in
``$XDG_STATE_HOME/openconnect-saml/history.jsonl`` (falls back to
``~/.local/state/openconnect-saml/history.jsonl``). Rotates when the file
exceeds ``MAX_SIZE_BYTES``.

Each record is a JSON object with:

- ``timestamp`` — ISO 8601 UTC string
- ``event`` — one of ``connected``, ``disconnected``, ``reconnecting``, ``error``
- ``profile`` — profile name (or ``default``)
- ``server`` — VPN server URL/host
- ``user`` — username (never credentials)
- ``duration_seconds`` — session duration (for ``disconnected`` events)
- ``message`` — free-text context (optional)
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger()

APP_NAME = "openconnect-saml"
# Conservative rotation threshold — ~500 KB (plenty for thousands of entries)
MAX_SIZE_BYTES = 512 * 1024


def _state_dir() -> Path:
    xdg_state = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return base / APP_NAME


def history_path() -> Path:
    """Return the full path to the history file."""
    return _state_dir() / "history.jsonl"


def _rotate_if_needed(path: Path) -> None:
    """Rotate the history file if it exceeds the size limit."""
    try:
        if path.exists() and path.stat().st_size > MAX_SIZE_BYTES:
            backup = path.with_suffix(".jsonl.old")
            if backup.exists():
                backup.unlink()
            path.rename(backup)
            logger.debug("Rotated history file", path=str(path))
    except OSError as exc:
        logger.warning("History rotation failed", error=str(exc))


@dataclass
class HistoryEntry:
    """A single history event."""

    event: str
    server: str
    profile: str = "default"
    user: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    duration_seconds: float | None = None
    message: str = ""


def log_event(
    event: str,
    server: str,
    profile: str = "default",
    user: str = "",
    duration_seconds: float | None = None,
    message: str = "",
) -> None:
    """Append an event to the history log."""
    path = history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        logger.debug("Cannot create history directory", error=str(exc))
        return

    _rotate_if_needed(path)

    entry = HistoryEntry(
        event=event,
        server=server,
        profile=profile,
        user=user,
        duration_seconds=duration_seconds,
        message=message,
    )

    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), separators=(",", ":")) + "\n")
        # Ensure restrictive permissions (owner-only)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except OSError as exc:
        logger.debug("Cannot write to history", error=str(exc))


def read_history(limit: int | None = None) -> list[dict]:
    """Read all history entries (newest last). Returns a list of dicts."""
    path = history_path()
    if not path.exists():
        return []

    entries: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []

    if limit is not None and limit > 0:
        entries = entries[-limit:]
    return entries


def clear_history() -> bool:
    """Delete the history file. Returns True if it existed, False otherwise."""
    path = history_path()
    try:
        if path.exists():
            path.unlink()
            return True
    except OSError as exc:
        logger.warning("Cannot clear history", error=str(exc))
    return False


# ---------------------------------------------------------------------------
# Connection tracker — used by app.py to emit start/end events
# ---------------------------------------------------------------------------


class ConnectionTracker:
    """Tracks the lifetime of a VPN session and emits history events."""

    def __init__(self, server: str, profile: str = "default", user: str = ""):
        self.server = server
        self.profile = profile
        self.user = user
        self._start: float | None = None

    def start(self) -> None:
        self._start = time.monotonic()
        log_event("connected", self.server, self.profile, self.user)

    def stop(self, reason: str = "") -> None:
        duration = None
        if self._start is not None:
            duration = round(time.monotonic() - self._start, 1)
            self._start = None
        log_event(
            "disconnected",
            self.server,
            self.profile,
            self.user,
            duration_seconds=duration,
            message=reason,
        )

    def reconnecting(self, attempt: int, delay: int) -> None:
        log_event(
            "reconnecting",
            self.server,
            self.profile,
            self.user,
            message=f"attempt={attempt} delay={delay}s",
        )

    def error(self, message: str) -> None:
        log_event(
            "error",
            self.server,
            self.profile,
            self.user,
            message=message,
        )


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m{int(seconds % 60)}s"
    hours = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    return f"{hours}h{mins:02d}m"


def _format_timestamp(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return iso


def handle_history_command(args) -> int:
    """Dispatch the ``history`` subcommand."""
    action = getattr(args, "history_action", None) or "show"

    if action == "clear":
        if clear_history():
            print("History cleared.")
        else:
            print("History was already empty.")
        return 0

    if action == "path":
        print(history_path())
        return 0

    # Default: show
    limit = getattr(args, "limit", None)
    entries = read_history(limit=limit)

    if not entries:
        print("No history entries yet.")
        print(f"(Log file: {history_path()})")
        return 0

    # Reverse so newest is first
    entries = list(reversed(entries))

    if getattr(args, "json", False):
        print(json.dumps(entries, indent=2))
        return 0

    print(f"{'When':<20}  {'Event':<14}  {'Profile':<14}  {'Duration':<10}  Server")
    print("-" * 90)
    for entry in entries:
        when = _format_timestamp(entry.get("timestamp", ""))
        event = entry.get("event", "?")
        profile = entry.get("profile", "-") or "-"
        duration = _format_duration(entry.get("duration_seconds"))
        server = entry.get("server", "?")
        msg = entry.get("message", "")
        line = f"{when:<20}  {event:<14}  {profile:<14}  {duration:<10}  {server}"
        if msg:
            line += f"  [{msg}]"
        print(line)

    return 0
