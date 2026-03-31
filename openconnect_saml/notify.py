"""Desktop notifications for openconnect-saml.

Sends notifications on VPN events (connect, disconnect, reconnect, error).
Supports Linux (notify-send/libnotify), macOS (osascript), and falls back
to terminal bell.

Enable via CLI ``--notify`` or config ``notifications = true``.
"""

from __future__ import annotations

import platform
import shutil
import subprocess  # nosec

import structlog

logger = structlog.get_logger()

APP_NAME = "openconnect-saml"


class NotificationLevel:
    """Notification severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


def _notify_linux(title: str, message: str, level: str = NotificationLevel.INFO) -> bool:
    """Send notification via notify-send (libnotify) on Linux."""
    notify_send = shutil.which("notify-send")
    if not notify_send:
        return False

    urgency_map = {
        NotificationLevel.INFO: "normal",
        NotificationLevel.WARNING: "normal",
        NotificationLevel.ERROR: "critical",
    }
    urgency = urgency_map.get(level, "normal")

    try:
        subprocess.run(  # nosec
            [notify_send, f"--urgency={urgency}", "--app-name", APP_NAME, title, message],
            timeout=5,
            capture_output=True,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _notify_macos(title: str, message: str, level: str = NotificationLevel.INFO) -> bool:
    """Send notification via osascript on macOS."""
    osascript = shutil.which("osascript")
    if not osascript:
        return False

    # Escape for AppleScript string
    safe_title = title.replace('"', '\\"')
    safe_message = message.replace('"', '\\"')

    script = (
        f'display notification "{safe_message}" with title "{safe_title}" subtitle "{APP_NAME}"'
    )

    try:
        subprocess.run(  # nosec
            [osascript, "-e", script],
            timeout=5,
            capture_output=True,
        )
        return True
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _notify_bell(title: str, message: str, level: str = NotificationLevel.INFO) -> bool:
    """Fallback: terminal bell character."""
    print(f"\a[{APP_NAME}] {title}: {message}")
    return True


def send_notification(
    title: str,
    message: str,
    level: str = NotificationLevel.INFO,
) -> bool:
    """Send a desktop notification using the best available method.

    Tries platform-specific methods first, falls back to terminal bell.

    Parameters
    ----------
    title : str
        Notification title.
    message : str
        Notification body text.
    level : str
        Severity level (info, warning, error).

    Returns
    -------
    bool
        True if notification was sent successfully.
    """
    system = platform.system()

    if system == "Linux":
        if _notify_linux(title, message, level):
            return True
    elif system == "Darwin" and _notify_macos(title, message, level):
        return True

    # Fallback
    return _notify_bell(title, message, level)


def notify_connected(server: str, profile: str | None = None) -> None:
    """Send 'Connected' notification."""
    msg = f"Connected to {server}"
    if profile:
        msg += f" (profile: {profile})"
    send_notification("🔐 VPN Connected", msg, NotificationLevel.INFO)
    logger.info("VPN connected notification sent", server=server)


def notify_disconnected(server: str, profile: str | None = None) -> None:
    """Send 'Disconnected' notification."""
    msg = f"Disconnected from {server}"
    if profile:
        msg += f" (profile: {profile})"
    send_notification("🔓 VPN Disconnected", msg, NotificationLevel.WARNING)
    logger.info("VPN disconnected notification sent", server=server)


def notify_reconnecting(server: str, attempt: int, delay: int) -> None:
    """Send 'Reconnecting' notification."""
    msg = f"Connection to {server} dropped. Reconnecting in {delay}s (attempt #{attempt})"
    send_notification("🔄 VPN Reconnecting", msg, NotificationLevel.WARNING)
    logger.info("VPN reconnecting notification sent", server=server, attempt=attempt)


def notify_error(server: str, error: str) -> None:
    """Send 'Error' notification."""
    msg = f"VPN error for {server}: {error}"
    send_notification("❌ VPN Error", msg, NotificationLevel.ERROR)
    logger.info("VPN error notification sent", server=server)
