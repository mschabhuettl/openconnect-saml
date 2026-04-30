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


def read_history(
    limit: int | None = None,
    *,
    profile: str | None = None,
    event: str | None = None,
    since: str | None = None,
) -> list[dict]:
    """Read history entries (newest last) with optional filters.

    Parameters
    ----------
    limit
        Keep only the most recent ``limit`` entries (after filtering).
    profile
        Match an exact ``profile`` field.
    event
        Match an exact ``event`` field (``connected``, ``disconnected``,
        ``reconnecting``, ``error``).
    since
        Drop entries with ``timestamp`` older than this point in time.
        Accepts an ISO 8601 string (``2026-04-30T12:00:00+00:00``) or
        a relative phrase like ``"1 day ago"`` / ``"2 hours ago"`` /
        ``"30 minutes ago"``.
    """
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

    if profile is not None:
        entries = [e for e in entries if e.get("profile") == profile]
    if event is not None:
        entries = [e for e in entries if e.get("event") == event]
    if since is not None:
        cutoff = _parse_since(since)
        if cutoff is not None:
            entries = [e for e in entries if _timestamp_after(e.get("timestamp"), cutoff)]

    if limit is not None and limit > 0:
        entries = entries[-limit:]
    return entries


def _parse_since(value: str) -> datetime | None:
    """Convert a since= string into a UTC datetime, or None if unparseable."""
    value = value.strip()
    # Relative? "<N> <unit>(s) ago" — minutes/hours/days
    parts = value.split()
    if len(parts) == 3 and parts[2] == "ago":
        try:
            n = int(parts[0])
        except ValueError:
            return None
        unit = parts[1].rstrip("s")
        delta_seconds = {
            "second": n,
            "minute": n * 60,
            "hour": n * 3600,
            "day": n * 86400,
            "week": n * 7 * 86400,
        }.get(unit)
        if delta_seconds is None:
            return None
        from datetime import timedelta

        return datetime.now(tz=timezone.utc) - timedelta(seconds=delta_seconds)
    # Otherwise parse ISO 8601 directly
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _timestamp_after(ts: str | None, cutoff: datetime) -> bool:
    if not ts:
        return False
    try:
        when = datetime.fromisoformat(ts)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when >= cutoff


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


def compute_stats(entries: list[dict]) -> dict:
    """Aggregate history entries into a summary suitable for ``history stats``.

    Returns a dict with:

    - ``total_connections`` — count of ``connected`` events
    - ``total_seconds`` — sum of ``duration_seconds`` across ``disconnected`` events
    - ``avg_seconds`` — mean session duration (only over completed sessions)
    - ``error_count`` — count of ``error`` events
    - ``profiles`` — list of {name, count} sorted by count desc
    - ``most_used_profile`` — convenience accessor for the top profile
    - ``last_connected`` — ISO timestamp of the most recent ``connected`` event
    - ``first_seen`` / ``last_seen`` — bounds of the log window
    """
    total_connections = 0
    error_count = 0
    durations: list[float] = []
    profiles: dict[str, int] = {}
    last_connected: str | None = None
    timestamps: list[str] = []

    for e in entries:
        ts = e.get("timestamp")
        if ts:
            timestamps.append(ts)
        ev = e.get("event")
        if ev == "connected":
            total_connections += 1
            prof = e.get("profile") or "default"
            profiles[prof] = profiles.get(prof, 0) + 1
            if last_connected is None or (ts and ts > last_connected):
                last_connected = ts
        elif ev == "disconnected":
            d = e.get("duration_seconds")
            if isinstance(d, (int, float)):
                durations.append(float(d))
        elif ev == "error":
            error_count += 1

    profile_list = [
        {"name": n, "count": c} for n, c in sorted(profiles.items(), key=lambda kv: -kv[1])
    ]
    total_seconds = round(sum(durations), 1)
    avg_seconds = round(total_seconds / len(durations), 1) if durations else 0.0

    return {
        "total_connections": total_connections,
        "total_seconds": total_seconds,
        "avg_seconds": avg_seconds,
        "error_count": error_count,
        "profiles": profile_list,
        "most_used_profile": profile_list[0]["name"] if profile_list else None,
        "last_connected": last_connected,
        "first_seen": min(timestamps) if timestamps else None,
        "last_seen": max(timestamps) if timestamps else None,
    }


def _export_history(args) -> int:
    """Write the connection history to a CSV or JSON file (or stdout)."""
    import csv
    import sys
    from io import StringIO

    fmt = (getattr(args, "format", None) or "csv").lower()
    target = getattr(args, "file", None)
    entries = read_history()

    if fmt not in ("csv", "json"):
        print(f"Error: unsupported format '{fmt}' (choose csv or json)", file=sys.stderr)
        return 1

    if fmt == "json":
        payload = json.dumps(entries, indent=2, default=str)
        if target and target != "-":
            Path(target).write_text(payload)
            print(f"✓ Wrote {len(entries)} entries to {target}")
        else:
            print(payload)
        return 0

    columns = ["timestamp", "event", "profile", "user", "server", "duration_seconds", "message"]
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for e in entries:
        writer.writerow({c: e.get(c, "") for c in columns})

    text = buf.getvalue()
    if target and target != "-":
        Path(target).write_text(text)
        print(f"✓ Wrote {len(entries)} entries to {target}")
    else:
        sys.stdout.write(text)
    return 0


def _print_stats(stats: dict) -> None:
    print("Connection statistics")
    print("-" * 40)
    print(f"  Total connections : {stats['total_connections']}")
    print(f"  Total time        : {_format_duration(stats['total_seconds'])}")
    print(f"  Average duration  : {_format_duration(stats['avg_seconds'])}")
    print(f"  Errors            : {stats['error_count']}")
    if stats["last_connected"]:
        print(f"  Last connected    : {_format_timestamp(stats['last_connected'])}")
    if stats["profiles"]:
        print()
        print("  Profile usage:")
        for p in stats["profiles"]:
            print(f"    {p['name']:<20} {p['count']}")


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

    if action == "stats":
        entries = read_history()
        stats = compute_stats(entries)
        if getattr(args, "json", False):
            print(json.dumps(stats, indent=2))
        else:
            _print_stats(stats)
        return 0

    if action == "export":
        return _export_history(args)

    # Default: show
    limit = getattr(args, "limit", None)
    entries = read_history(
        limit=limit,
        profile=getattr(args, "filter_profile", None),
        event=getattr(args, "filter_event", None),
        since=getattr(args, "since", None),
    )

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
