"""PyPI version check.

``openconnect-saml --version --check`` (and ``openconnect-saml doctor``)
hit PyPI's JSON endpoint to surface a "newer version available" hint.
The check is best-effort with a hard 3 second timeout, never raises,
and always falls back gracefully if PyPI is unreachable.

The module deliberately doesn't cache results — a CLI invocation that
fails offline shouldn't be slowed down by stale cache logic, and the
check is rare enough that "fresh data on demand" is the right
default.
"""

from __future__ import annotations

from dataclasses import dataclass

PYPI_URL = "https://pypi.org/pypi/openconnect-saml/json"
TIMEOUT_S = 3.0


@dataclass
class VersionInfo:
    installed: str
    latest: str | None
    is_outdated: bool

    def hint_line(self) -> str | None:
        if self.is_outdated and self.latest:
            return (
                f"Newer release available: {self.latest}\n"
                f"Update with: pip install --upgrade openconnect-saml"
            )
        return None


def _parse_version(s: str) -> tuple[int, ...]:
    """Best-effort tuple parse of dotted-numeric versions ('0.14.0' → (0, 14, 0))."""
    parts: list[int] = []
    for chunk in s.split("."):
        head: list[str] = []
        for ch in chunk:
            if ch.isdigit():
                head.append(ch)
            else:
                break
        if head:
            parts.append(int("".join(head)))
        else:
            break
    return tuple(parts)


def get_latest_pypi_version() -> str | None:
    """Best-effort lookup of the most recent release on PyPI. Returns None on
    any failure (network, timeout, malformed response)."""
    try:
        import requests
    except ImportError:
        return None
    try:
        resp = requests.get(PYPI_URL, timeout=TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001 — best effort
        return None
    info = data.get("info") if isinstance(data, dict) else None
    if not isinstance(info, dict):
        return None
    version = info.get("version")
    return str(version) if isinstance(version, str) else None


def check() -> VersionInfo:
    """Compare installed version against PyPI."""
    from openconnect_saml import __version__

    installed = __version__
    latest = get_latest_pypi_version()
    if latest is None:
        return VersionInfo(installed=installed, latest=None, is_outdated=False)
    return VersionInfo(
        installed=installed,
        latest=latest,
        is_outdated=_parse_version(latest) > _parse_version(installed),
    )
