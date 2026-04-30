"""Multi-session tracking for openconnect-saml.

Records which `openconnect` processes were started by us, keyed by
profile name. Lets ``openconnect-saml status`` enumerate every active
tunnel and ``openconnect-saml disconnect <profile>`` find and stop a
specific one without grepping the process list.

State lives in ``$XDG_STATE_HOME/openconnect-saml/sessions/<profile>.json``,
mode 0600. Each file contains:

- ``profile`` — profile name (or ``"default"``)
- ``server`` — VPN gateway URL / host
- ``user`` — username (no secrets ever)
- ``pid`` — pid of the openconnect process
- ``started_at`` — ISO 8601 UTC timestamp
- ``interface`` — tunnel interface name when known (filled in best-effort)
- ``parent_pid`` — pid of the openconnect-saml supervisor (if detached)

Stale records (pid no longer running) are pruned on read.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import structlog

logger = structlog.get_logger()

APP_NAME = "openconnect-saml"


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_NAME / "sessions"


def _safe_name(profile: str) -> str:
    """Turn a profile name into a safe filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", profile or "default")
    return cleaned or "default"


def session_file(profile: str) -> Path:
    return _state_dir() / f"{_safe_name(profile)}.json"


@dataclass
class Session:
    profile: str
    server: str
    user: str = ""
    pid: int = 0
    parent_pid: int = 0
    interface: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, d: dict) -> Session:
        return cls(
            profile=str(d.get("profile", "default")),
            server=str(d.get("server", "")),
            user=str(d.get("user", "")),
            pid=int(d.get("pid", 0)),
            parent_pid=int(d.get("parent_pid", 0)),
            interface=str(d.get("interface", "")),
            started_at=str(d.get("started_at", "")),
        )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Another user's process — still considered alive
        return True
    return True


def record(session: Session) -> Path:
    """Persist a session record. Creates the state directory if needed."""
    state_dir = _state_dir()
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = session_file(session.profile)
    try:
        path.write_text(json.dumps(asdict(session), separators=(",", ":")))
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning("Cannot persist session record", profile=session.profile, error=str(exc))
    return path


def load(profile: str) -> Session | None:
    """Load a single session record by profile, or None if stale / missing."""
    path = session_file(profile)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    sess = Session.from_dict(data)
    if not _pid_alive(sess.pid):
        # Stale — clean up
        with contextlib.suppress(OSError):
            path.unlink()
        return None
    return sess


def list_active() -> list[Session]:
    """Return every live session, pruning stale records on the way."""
    state_dir = _state_dir()
    if not state_dir.exists():
        return []
    sessions: list[Session] = []
    for path in sorted(state_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        sess = Session.from_dict(data)
        if _pid_alive(sess.pid):
            sessions.append(sess)
        else:
            with contextlib.suppress(OSError):
                path.unlink()
    return sessions


def remove(profile: str) -> bool:
    """Delete a session record (regardless of pid liveness). Returns True if existed."""
    path = session_file(profile)
    if path.exists():
        with contextlib.suppress(OSError):
            path.unlink()
        return True
    return False


def kill(profile: str, *, timeout: float = 10.0) -> bool:
    """Send SIGTERM to the recorded openconnect process for ``profile``.

    Waits up to ``timeout`` seconds for it to exit (then SIGKILL). Returns
    True if a process was found and signalled, False if no live record.
    """
    sess = load(profile)
    if not sess:
        return False
    try:
        os.kill(sess.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        remove(profile)
        return False

    deadline = time.monotonic() + timeout
    while _pid_alive(sess.pid) and time.monotonic() < deadline:
        time.sleep(0.1)

    if _pid_alive(sess.pid):
        # Still alive — escalate to SIGKILL
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(sess.pid, signal.SIGKILL)

    remove(profile)
    return True
