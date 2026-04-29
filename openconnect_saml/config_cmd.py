"""`config` subcommand — inspect and validate the config file.

Provides:

- ``config show`` — print the current configuration (with secrets redacted)
- ``config path`` — print the config file path
- ``config validate`` — syntactically and semantically check the config
- ``config edit`` — open the config file in ``$EDITOR``

Does not reinvent TOML editing; ``edit`` just launches the user's editor.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec
import sys
from pathlib import Path

import toml
import xdg.BaseDirectory

from openconnect_saml import config

APP_NAME = "openconnect-saml"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def resolve_config_path(create: bool = False) -> Path:
    """Return the config file path, optionally creating the dir."""
    if create:
        base = xdg.BaseDirectory.save_config_path(APP_NAME)
    else:
        base = xdg.BaseDirectory.load_first_config(APP_NAME)
        if not base:
            base = os.path.join(
                os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")),
                APP_NAME,
            )
    return Path(base) / "config.toml"


# ---------------------------------------------------------------------------
# Secret redaction
# ---------------------------------------------------------------------------


# Keys whose values should be redacted when shown. Matched case-insensitively
# as substrings against the key name.
_SECRET_KEY_HINTS = (
    "password", "token", "secret", "session", "api_key", "apikey",
)


def _should_redact(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _SECRET_KEY_HINTS)


def _redact(data):
    """Recursively redact secret values in a nested structure."""
    if isinstance(data, dict):
        return {
            k: ("***" if _should_redact(k) and v else _redact(v)) for k, v in data.items()
        }
    if isinstance(data, list):
        return [_redact(v) for v in data]
    return data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_config(path: Path) -> list[tuple[str, str]]:
    """Validate the config file. Returns a list of (severity, message) tuples.

    Severities: ``error``, ``warning``, ``info``.
    An empty list means the config is fully valid.
    """
    issues: list[tuple[str, str]] = []

    if not path.exists():
        issues.append(("error", f"Config file not found: {path}"))
        return issues

    # Permissions check
    if os.name == "posix":
        mode = path.stat().st_mode & 0o777
        if mode & 0o077:
            issues.append((
                "warning",
                f"Config file has overly permissive mode {oct(mode)} (should be 0600)",
            ))

    # Parse TOML
    try:
        raw = toml.loads(path.read_text())
    except toml.TomlDecodeError as exc:
        issues.append(("error", f"Invalid TOML syntax: {exc}"))
        return issues
    except OSError as exc:
        issues.append(("error", f"Cannot read config file: {exc}"))
        return issues

    # Load via Config — this catches schema errors
    try:
        cfg = config.Config.from_dict(raw)
    except Exception as exc:
        issues.append(("error", f"Config schema error: {exc}"))
        return issues

    # Semantic checks
    profiles = raw.get("profiles", {})
    if not isinstance(profiles, dict):
        issues.append(("error", "'profiles' must be a table"))
    else:
        for name, prof in profiles.items():
            if not isinstance(prof, dict):
                issues.append(("error", f"profile '{name}' is not a table"))
                continue
            if not prof.get("server"):
                issues.append(("error", f"profile '{name}' missing 'server' field"))
            creds = prof.get("credentials", {})
            if isinstance(creds, dict):
                src = creds.get("totp_source", "local")
                if src == "2fauth":
                    prof_twofa = prof.get("2fauth") or raw.get("2fauth")
                    if not prof_twofa:
                        issues.append((
                            "warning",
                            f"profile '{name}' uses 2fauth but no [2fauth] config found",
                        ))
                elif src == "bitwarden":
                    prof_bw = prof.get("bitwarden") or raw.get("bitwarden")
                    if not prof_bw:
                        issues.append((
                            "warning",
                            f"profile '{name}' uses bitwarden but no [bitwarden] config found",
                        ))

    active = raw.get("active_profile")
    if active and active not in profiles:
        issues.append((
            "warning",
            f"'active_profile' is set to '{active}' but no such profile exists",
        ))

    # Default profile sanity
    dp = raw.get("default_profile")
    if dp and isinstance(dp, dict) and not dp.get("address"):
        issues.append(("error", "'default_profile' is missing 'address'"))

    # Timeout / port ranges
    if "timeout" in raw and not (isinstance(raw["timeout"], int) and raw["timeout"] > 0):
        issues.append(("error", "'timeout' must be a positive integer"))

    # Routes format — simple CIDR-ish check
    for name, prof in profiles.items() if isinstance(profiles, dict) else []:
        if not isinstance(prof, dict):
            continue
        for field in ("routes", "no_routes"):
            for route in prof.get(field, []) or []:
                if not isinstance(route, str) or "/" not in route:
                    issues.append((
                        "warning",
                        f"profile '{name}' has invalid CIDR in {field}: {route!r}",
                    ))

    _ = cfg  # silence unused
    return issues


# ---------------------------------------------------------------------------
# CLI handlers
# ---------------------------------------------------------------------------


def _cmd_path() -> int:
    print(resolve_config_path())
    return 0


def _cmd_show(as_json: bool = False) -> int:
    path = resolve_config_path()
    if not path.exists():
        print(f"No config file at {path}")
        return 1
    try:
        data = toml.loads(path.read_text())
    except Exception as exc:
        print(f"Error reading config: {exc}", file=sys.stderr)
        return 1
    redacted = _redact(data)
    if as_json:
        print(json.dumps(redacted, indent=2, default=str))
    else:
        print(toml.dumps(redacted))
    print(f"# (path: {path}; secrets redacted)")
    return 0


def _cmd_validate() -> int:
    path = resolve_config_path()
    issues = validate_config(path)
    if not issues:
        print(f"✓ Config at {path} is valid.")
        return 0
    errors = [i for i in issues if i[0] == "error"]
    warnings = [i for i in issues if i[0] == "warning"]
    for severity, msg in issues:
        prefix = {"error": "✗", "warning": "!", "info": "i"}.get(severity, " ")
        print(f"  [{prefix}] {severity}: {msg}")
    print()
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s).")
    return 1 if errors else 0


def _cmd_edit() -> int:
    path = resolve_config_path(create=True)
    if not path.exists():
        path.touch(mode=0o600)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        for candidate in ("nano", "vim", "vi"):
            if shutil.which(candidate):
                editor = candidate
                break
    if not editor:
        print("Error: no editor found. Set $EDITOR or install nano/vim.", file=sys.stderr)
        return 1
    return subprocess.call([editor, str(path)])  # nosec


def handle_config_command(args) -> int:
    """Dispatch the ``config`` subcommand."""
    action = getattr(args, "config_action", None)
    if action == "path":
        return _cmd_path()
    if action == "show":
        return _cmd_show(as_json=getattr(args, "json", False))
    if action == "validate":
        return _cmd_validate()
    if action == "edit":
        return _cmd_edit()
    print(f"Unknown config action: {action}")
    return 1
