"""Multi-profile management for openconnect-saml.

Provides CLI handlers for listing, adding, removing, exporting, and importing
named VPN profiles from the configuration file.

Export/import default format is plain JSON for portability — a single profile is a
JSON object; multiple profiles exported at once are wrapped in a top-level
``{"profiles": {...}}`` envelope.

Profiles can also be exported as a NetworkManager ``.nmconnection`` file
(``--format nmconnection``) that can be dropped into
``/etc/NetworkManager/system-connections/`` to import the profile into the
Ubuntu/GNOME VPN UI (#22). The generated file uses the
``org.freedesktop.NetworkManager.openconnect`` plugin and contains no secrets.
"""

from __future__ import annotations

import json
import sys
import uuid as _uuid
from pathlib import Path

from openconnect_saml import config


def _prompt_for_decrypt_passphrase() -> str:
    import getpass

    return getpass.getpass("Backup passphrase: ")


def handle_profiles_command(args):
    """Dispatch profiles subcommands."""
    action = getattr(args, "profiles_action", None)

    if action == "add":
        return _add_profile(args)
    if action == "remove":
        return _remove_profile(args)
    if action == "export":
        return _export_profile(args)
    if action == "import":
        return _import_profile(args)
    if action == "import-xml":
        return _import_xml_profile(args)
    if action == "rename":
        return _rename_profile(args)
    if action == "show":
        return _show_profile(args)
    if action == "migrate":
        return _migrate_profiles(args)
    if action == "set":
        return _set_profile_field(args)
    if action == "copy":
        return _copy_profile(args)
    # Default: list profiles
    return _list_profiles()


def _copy_profile(args):
    """Duplicate a profile under a new name. Refuses to overwrite existing
    targets unless ``--force`` is given."""
    cfg = config.load()
    src = args.source
    dst = args.dest
    overwrite = getattr(args, "force", False)

    prof = cfg.get_profile(src)
    if prof is None:
        print(f"Error: source profile '{src}' not found.", file=sys.stderr)
        return 1
    if dst in cfg.profiles and not overwrite:
        print(
            f"Error: target profile '{dst}' already exists (use --force to overwrite).",
            file=sys.stderr,
        )
        return 1

    cfg.add_profile(dst, prof.as_dict())
    config.save(cfg)
    print(f"Copied '{src}' → '{dst}'.")
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _list_profiles():
    """List all configured profiles."""
    cfg = config.load()
    profiles = cfg.list_profiles()

    if not profiles:
        print("No profiles configured.")
        print()
        print("Add a profile:")
        print("  openconnect-saml profiles add <name> --server vpn.example.com")
        return 0

    print(f"{'Name':<20} {'Server':<35} {'User':<25} {'Group'}")
    print("-" * 100)
    for name, prof in profiles:
        user = prof.credentials.username if prof.credentials else ""
        group = prof.user_group or ""
        marker = " *" if name == cfg.active_profile else ""
        print(f"{name + marker:<20} {prof.server:<35} {user:<25} {group}")

    if cfg.active_profile:
        print(f"\n* = active profile ({cfg.active_profile})")

    return 0


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


def _add_profile(args):
    """Add or update a named profile."""
    cfg = config.load()
    name = args.profile_name

    server = getattr(args, "server", None)
    if not server:
        try:
            server = input(f"Server for '{name}': ").strip()
            if not server:
                print("Error: server is required.", file=sys.stderr)
                return 1
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1

    user_group = getattr(args, "user_group", "") or ""
    display_name = getattr(args, "display_name", "") or ""
    username = getattr(args, "user", None)
    totp_source = getattr(args, "totp_source", None)

    if not username:
        try:
            username = input("Username (leave empty to skip): ").strip() or None
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1

    if not user_group:
        try:
            user_group = input("User group (leave empty to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            return 1

    if not display_name:
        display_name = name

    profile_data = {
        "server": server,
        "user_group": user_group,
        "name": display_name,
    }

    if username:
        cred_data = {"username": username}
        if totp_source:
            cred_data["totp_source"] = totp_source
        profile_data["credentials"] = cred_data

    browser = getattr(args, "browser", None)
    if browser:
        profile_data["browser"] = browser
    notify = getattr(args, "notify", None)
    if notify is not None:
        profile_data["notify"] = bool(notify)

    existed = name in cfg.profiles
    cfg.add_profile(name, profile_data)
    config.save(cfg)

    action = "Updated" if existed else "Added"
    print(f"{action} profile '{name}' → {server}")
    return 0


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


def _remove_profile(args):
    """Remove a named profile."""
    cfg = config.load()
    name = args.profile_name

    if not cfg.remove_profile(name):
        print(f"Error: profile '{name}' not found.", file=sys.stderr)
        available = cfg.list_profiles()
        if available:
            print("Available profiles:", file=sys.stderr)
            for pname, _ in available:
                print(f"  - {pname}", file=sys.stderr)
        return 1

    if cfg.active_profile == name:
        cfg.active_profile = None

    config.save(cfg)
    print(f"Removed profile '{name}'.")
    return 0


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def _rename_profile(args):
    """Rename a profile."""
    cfg = config.load()
    old = args.profile_name
    new = getattr(args, "new_name", None)

    if not new:
        print("Error: --to/new name is required.", file=sys.stderr)
        return 1
    if old not in cfg.profiles:
        print(f"Error: profile '{old}' not found.", file=sys.stderr)
        return 1
    if new in cfg.profiles:
        print(f"Error: profile '{new}' already exists.", file=sys.stderr)
        return 1

    cfg.profiles[new] = cfg.profiles.pop(old)
    if cfg.active_profile == old:
        cfg.active_profile = new
    config.save(cfg)
    print(f"Renamed profile '{old}' → '{new}'.")
    return 0


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


def _show_profile(args):
    """Show a single profile's details."""
    cfg = config.load()
    name = args.profile_name
    prof = cfg.get_profile(name)
    if not prof:
        print(f"Error: profile '{name}' not found.", file=sys.stderr)
        return 1
    data = prof.as_dict()
    # Redact any sensitive fields
    if "credentials" in data and isinstance(data["credentials"], dict):
        creds = data["credentials"]
        for key in list(creds):
            if (
                "password" in key.lower() or "token" in key.lower() or "secret" in key.lower()
            ) and creds[key]:
                creds[key] = "***"
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2, default=str))
    else:
        for k, v in data.items():
            print(f"  {k}: {v}")
    return 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def _profile_to_exportable(name: str, prof) -> dict:
    """Turn a profile into a JSON-safe dict, redacting secrets."""
    data = prof.as_dict() if hasattr(prof, "as_dict") else dict(prof)
    data["_name"] = name
    # Strip credentials that contain secrets — export usernames but never
    # tokens/passwords
    if "credentials" in data and isinstance(data["credentials"], dict):
        creds = dict(data["credentials"])
        for key in list(creds):
            if key.lower() in ("password", "totp", "totp_secret"):
                creds.pop(key, None)
        data["credentials"] = creds
    # Export 2fauth / bitwarden metadata WITHOUT the token
    if "2fauth" in data and isinstance(data["2fauth"], dict):
        twofa = dict(data["2fauth"])
        twofa.pop("token", None)
        data["2fauth"] = twofa
    return data


# ---------------------------------------------------------------------------
# set — programmatically modify a profile field
# ---------------------------------------------------------------------------


# Fields the user is allowed to edit via ``profiles set``. Booleans coerce
# from string, ints likewise; everything else is treated as plain text.
_SETTABLE_FIELDS: dict[str, str] = {
    "server": "str",
    "user_group": "str",
    "name": "str",
    "browser": "str_or_clear",
    "notify": "bool_or_clear",
    "on_connect": "str_or_clear",
    "on_disconnect": "str_or_clear",
    "cert": "str_or_clear",
    "cert_key": "str_or_clear",
    # nested credentials.* shortcut
    "username": "str_or_clear",
    "totp_source": "str_or_clear",
}


def _set_profile_field(args):
    """Set a single field on a saved profile.

    Empty value (``""``) clears optional/None-able fields. Unknown fields
    are rejected with a list of allowed names. Booleans accept
    ``true|false|yes|no|1|0``.
    """
    cfg = config.load()
    name = args.profile_name
    field = args.field
    raw_value = args.value

    if name not in cfg.profiles:
        print(f"Error: profile '{name}' not found.", file=sys.stderr)
        return 1
    if field not in _SETTABLE_FIELDS:
        print(
            f"Error: unsupported field '{field}'. Allowed: " + ", ".join(sorted(_SETTABLE_FIELDS)),
            file=sys.stderr,
        )
        return 1

    prof = cfg.get_profile(name)
    field_type = _SETTABLE_FIELDS[field]
    parsed: object

    is_clear = field_type.endswith("_or_clear") and raw_value == ""
    if field_type == "bool_or_clear":
        if is_clear:
            parsed = None
        else:
            lower = raw_value.lower()
            if lower in ("true", "yes", "1", "on", "y"):
                parsed = True
            elif lower in ("false", "no", "0", "off", "n"):
                parsed = False
            else:
                print(
                    f"Error: '{field}' takes a boolean (true/false), got '{raw_value}'",
                    file=sys.stderr,
                )
                return 1
    else:  # str / str_or_clear
        parsed = None if is_clear else raw_value

    if field in ("username", "totp_source"):
        # Nested credentials field
        if prof.credentials is None:
            from openconnect_saml.config import Credentials

            prof.credentials = Credentials(username="")
        if parsed is None:
            # username can't really be None; clearing means "remove credentials"
            if field == "username":
                prof.credentials = None
            else:
                # totp_source default = "local"
                prof.credentials.totp_source = "local"
        else:
            setattr(prof.credentials, field, parsed)
    else:
        setattr(prof, field, parsed)

    config.save(cfg)
    if parsed is None:
        print(f"Cleared {name}.{field}.")
    else:
        print(f"Set {name}.{field} = {parsed!r}.")
    return 0


# ---------------------------------------------------------------------------
# import-xml — read Cisco AnyConnect .xml profiles and create entries
# ---------------------------------------------------------------------------


def _import_xml_profile(args):
    """Import VPN profiles from a Cisco AnyConnect ``.xml`` profile file.

    The format is the same one ``openconnect`` itself reads from
    ``/opt/cisco/anyconnect/profile/*.xml`` — it lists ``HostEntry`` blocks
    with HostName / HostAddress / UserGroup. We turn each entry into a
    saved openconnect-saml profile.

    Existing profiles with the same ``HostName`` are skipped unless
    ``--force`` is passed. ``--prefix STR`` prefixes every imported
    profile name (useful when bulk-importing multiple XML files).
    """
    source = getattr(args, "file", None)
    overwrite = getattr(args, "force", False)
    prefix = getattr(args, "prefix", "") or ""

    if not source or not Path(source).exists():
        print(f"Error: file '{source}' not found.", file=sys.stderr)
        return 1

    from openconnect_saml.profile import _get_profiles_from_one_file

    try:
        host_profiles = _get_profiles_from_one_file(Path(source))
    except Exception as exc:  # noqa: BLE001 — surface XML parser errors directly
        print(f"Error: failed to parse '{source}': {exc}", file=sys.stderr)
        return 1

    if not host_profiles:
        print(f"No HostEntry elements found in {source}.")
        return 1

    cfg = config.load()
    imported = 0
    skipped = 0
    for hp in host_profiles:
        # HostProfile.name maps to AnyConnect's HostName which is also the
        # display name; use it as the profile key.
        raw_name = (hp.name or hp.address or "").strip()
        if not raw_name:
            skipped += 1
            continue
        profile_key = f"{prefix}{raw_name}".replace(" ", "_")
        if profile_key in cfg.profiles and not overwrite:
            print(f"  - '{profile_key}' already exists (use --force to overwrite), skipping.")
            skipped += 1
            continue
        prof_data = {
            "server": hp.address,
            "user_group": hp.user_group or "",
            "name": raw_name,
        }
        cfg.add_profile(profile_key, prof_data)
        print(f"  ✓ imported '{profile_key}' → {hp.address}")
        imported += 1

    if imported:
        config.save(cfg)
    print(f"\nImported {imported} profile(s), skipped {skipped}.")
    return 0 if imported else 1


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


# Each entry: (description, predicate(cfg) -> bool, fix(cfg) -> None).
# Predicates and fixes operate on a loaded ``Config`` instance — the caller
# saves only when at least one fix has run.
_MIGRATIONS: list[tuple[str, callable, callable]] = []


def _register_migration(description: str):
    def _decorate(fn_pair):
        predicate, fix = fn_pair
        _MIGRATIONS.append((description, predicate, fix))
        return fn_pair

    return _decorate


def _legacy_default_profile_into_profiles_pair():
    """If only ``[default_profile]`` exists, mirror it into ``[profiles.default]``."""

    def predicate(cfg):
        return cfg.default_profile is not None and not cfg.profiles

    def fix(cfg):
        prof = config.ProfileConfig(
            server=cfg.default_profile.address,
            user_group=cfg.default_profile.user_group or "",
            name=cfg.default_profile.name or "default",
        )
        if cfg.credentials:
            prof.credentials = cfg.credentials
        cfg.profiles["default"] = prof
        if not cfg.active_profile:
            cfg.active_profile = "default"

    return predicate, fix


def _drop_unused_provider_sections_pair():
    """Drop ``[2fauth]`` / ``[bitwarden]`` / ``[1password]`` / ``[pass]`` sections
    that no profile references anymore."""
    sections = (
        ("twofauth", "totp_source", "2fauth"),
        ("bitwarden", "totp_source", "bitwarden"),
        ("onepassword", "totp_source", "1password"),
        ("pass_", "totp_source", "pass"),
    )

    def _referenced(cfg, source_name):
        if cfg.credentials and getattr(cfg.credentials, "totp_source", None) == source_name:
            return True
        for prof in cfg.profiles.values():
            if prof.credentials and getattr(prof.credentials, "totp_source", None) == source_name:
                return True
        return False

    def predicate(cfg):
        return any(
            getattr(cfg, attr) is not None and not _referenced(cfg, source_name)
            for attr, _, source_name in sections
        )

    def fix(cfg):
        for attr, _, source_name in sections:
            if getattr(cfg, attr) is not None and not _referenced(cfg, source_name):
                setattr(cfg, attr, None)

    return predicate, fix


_register_migration("Move legacy [default_profile] to [profiles.default] (multi-profile schema)")(
    _legacy_default_profile_into_profiles_pair()
)
_register_migration("Drop unused [2fauth] / [bitwarden] / [1password] / [pass] sections")(
    _drop_unused_provider_sections_pair()
)


def _bump_schema_version_pair():
    """Bring ``schema_version`` up to the current ``config.SCHEMA_VERSION``."""

    def predicate(cfg):
        return getattr(cfg, "schema_version", 1) != config.SCHEMA_VERSION

    def fix(cfg):
        cfg.schema_version = config.SCHEMA_VERSION

    return predicate, fix


_register_migration(f"Bump schema_version to {config.SCHEMA_VERSION}")(_bump_schema_version_pair())


def _migrate_profiles(args):
    """Apply schema fixups to the active config file.

    Each migration is a (predicate, fix) pair. The predicate returns True when
    the migration is applicable; the fix mutates the config in-place. We run
    in dry-run mode by default and only persist if ``--apply`` is passed.
    """
    apply = getattr(args, "apply", False)
    cfg = config.load()

    pending: list[str] = []
    for description, predicate, _fix in _MIGRATIONS:
        if predicate(cfg):
            pending.append(description)

    if not pending:
        print("No migrations needed; configuration is already up to date.")
        return 0

    print(f"{len(pending)} migration(s) applicable:")
    for desc in pending:
        print(f"  • {desc}")
    print()

    if not apply:
        print("Dry-run only. Re-run with --apply to persist changes.")
        return 0

    for _description, predicate, fix in _MIGRATIONS:
        if predicate(cfg):
            fix(cfg)
    config.save(cfg)
    print(f"✓ Applied {len(pending)} migration(s) to {config.config_path()}")
    return 0


def _profile_to_nmconnection(name: str, prof) -> str:
    """Render a profile as a NetworkManager ``.nmconnection`` file.

    The output uses the ``org.freedesktop.NetworkManager.openconnect`` plugin
    so it can be imported into NetworkManager / the Ubuntu VPN UI. The UUID
    is derived from the profile name so re-exporting the same profile
    overwrites the existing connection in NM rather than duplicating it.

    Secrets (passwords, TOTP) are not written; SAML/SSO authentication still
    happens at connect time via the openconnect plugin.
    """
    server = getattr(prof, "server", "") or ""
    user_group = getattr(prof, "user_group", "") or ""
    display_name = getattr(prof, "name", "") or name

    username = ""
    creds = getattr(prof, "credentials", None)
    if creds is not None:
        username = getattr(creds, "username", "") or ""

    gateway = server
    if "://" in gateway:
        gateway = gateway.split("://", 1)[1]
    gateway = gateway.rstrip("/")

    nm_uuid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"openconnect-saml://{name}"))

    lines = [
        "[connection]",
        f"id={display_name or name}",
        f"uuid={nm_uuid}",
        "type=vpn",
        "autoconnect=false",
        "",
        "[vpn]",
        "service-type=org.freedesktop.NetworkManager.openconnect",
        f"gateway={gateway}",
        "authtype=password",
        "protocol=anyconnect",
        "gateway-flags=2",
        "useragent-flags=0",
        "no_external_auth-flags=0",
    ]
    if user_group:
        lines.append(f"usergroup={user_group}")
    if username:
        lines.append(r"form\:main\:username-flags=0")
    lines.append("")

    if username:
        lines += [
            "[vpn-secrets]",
            f"form:main:username={username}",
            "",
        ]

    lines += [
        "[ipv4]",
        "method=auto",
        "",
        "[ipv6]",
        "method=auto",
        "",
    ]
    return "\n".join(lines)


def _export_profile(args):
    """Export one (or all) profiles to JSON, encrypted, or .nmconnection file(s)."""
    cfg = config.load()
    name = getattr(args, "profile_name", None)
    target = getattr(args, "file", None)
    fmt = (getattr(args, "format", None) or "json").lower()

    if fmt == "nmconnection":
        return _export_nmconnection(cfg, name, target)

    if name:
        prof = cfg.get_profile(name)
        if not prof:
            print(f"Error: profile '{name}' not found.", file=sys.stderr)
            return 1
        payload = {"version": 1, "profile": _profile_to_exportable(name, prof)}
    else:
        # All profiles
        payload = {
            "version": 1,
            "profiles": {n: _profile_to_exportable(n, p) for n, p in cfg.list_profiles()},
        }

    if fmt == "encrypted":
        from openconnect_saml.encrypted_backup import export_encrypted

        return export_encrypted(payload, Path(target) if target and target != "-" else None)

    text = json.dumps(payload, indent=2, default=str)
    if target and target != "-":
        path = Path(target)
        try:
            path.write_text(text)
            path.chmod(0o600)
        except OSError as exc:
            print(f"Error writing {path}: {exc}", file=sys.stderr)
            return 1
        print(f"✓ Exported to {path}")
    else:
        print(text)
    return 0


def _export_nmconnection(cfg, name, target):
    """Write one or more profiles as NetworkManager .nmconnection files."""
    profs: list[tuple[str, object]]
    if name:
        prof = cfg.get_profile(name)
        if not prof:
            print(f"Error: profile '{name}' not found.", file=sys.stderr)
            return 1
        profs = [(name, prof)]
    else:
        profs = list(cfg.list_profiles())
        if not profs:
            print("No profiles to export.", file=sys.stderr)
            return 1

    if not target or target == "-":
        # Stdout: only valid for a single profile, otherwise concat with separators
        if len(profs) > 1:
            print(
                "Error: --format nmconnection with multiple profiles requires --file <directory>.",
                file=sys.stderr,
            )
            return 1
        print(_profile_to_nmconnection(*profs[0]))
        return 0

    out_path = Path(target)
    if len(profs) == 1 and not out_path.is_dir():
        text = _profile_to_nmconnection(*profs[0])
        try:
            out_path.write_text(text)
            out_path.chmod(0o600)
        except OSError as exc:
            print(f"Error writing {out_path}: {exc}", file=sys.stderr)
            return 1
        print(f"✓ Exported to {out_path}")
        print("  Install with: sudo cp", out_path, "/etc/NetworkManager/system-connections/")
        print("  Then: sudo nmcli connection reload")
        return 0

    # Multiple profiles → write each into the directory
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"Error creating {out_path}: {exc}", file=sys.stderr)
        return 1
    for pname, prof in profs:
        fname = f"{pname}.nmconnection"
        path = out_path / fname
        try:
            path.write_text(_profile_to_nmconnection(pname, prof))
            path.chmod(0o600)
        except OSError as exc:
            print(f"Error writing {path}: {exc}", file=sys.stderr)
            return 1
        print(f"✓ Exported {pname} → {path}")
    return 0


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------


def _import_profile(args):
    """Import one or more profiles from a JSON file (or stdin).

    The file may be plain JSON or an encrypted backup produced by
    ``profiles export --format encrypted``. Format detection is
    automatic via the ``OPENCONNECT_SAML_BACKUP`` magic header.
    """
    source = getattr(args, "file", None)
    rename_to = getattr(args, "as_name", None)
    overwrite = getattr(args, "force", False)

    if not source or source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        if not path.exists():
            print(f"Error: file '{path}' not found.", file=sys.stderr)
            return 1
        text = path.read_text()

    if text.startswith("OPENCONNECT_SAML_BACKUP"):
        from openconnect_saml.encrypted_backup import decrypt

        try:
            text = decrypt(text.encode("utf-8"), _prompt_for_decrypt_passphrase()).decode("utf-8")
        except ValueError as exc:
            print(f"Error: cannot decrypt backup: {exc}", file=sys.stderr)
            return 1

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print("Error: top-level JSON must be an object.", file=sys.stderr)
        return 1

    # Accept either {"profile": {...}} or {"profiles": {name: {...}, ...}}
    # or a bare profile dict (legacy-friendly)
    profiles_to_add: list[tuple[str, dict]] = []

    if "profile" in payload:
        prof = payload["profile"]
        name = rename_to or prof.get("_name") or prof.get("name")
        if not name:
            print("Error: cannot determine profile name. Use --as <name>.", file=sys.stderr)
            return 1
        profiles_to_add.append((name, prof))
    elif "profiles" in payload and isinstance(payload["profiles"], dict):
        if rename_to and len(payload["profiles"]) > 1:
            print(
                "Error: --as cannot be used when importing multiple profiles.",
                file=sys.stderr,
            )
            return 1
        for pname, prof in payload["profiles"].items():
            effective_name = rename_to or pname
            profiles_to_add.append((effective_name, prof))
    elif "server" in payload:
        # Bare profile dict
        name = rename_to or payload.get("_name") or payload.get("name")
        if not name:
            print("Error: cannot determine profile name. Use --as <name>.", file=sys.stderr)
            return 1
        profiles_to_add.append((name, payload))
    else:
        print("Error: unrecognised import payload format.", file=sys.stderr)
        return 1

    cfg = config.load()
    imported = 0
    skipped = 0

    for name, prof_data in profiles_to_add:
        # Strip internal keys
        prof_data = {k: v for k, v in prof_data.items() if not k.startswith("_")}
        if name in cfg.profiles and not overwrite:
            print(f"  - '{name}' already exists (use --force to overwrite), skipping.")
            skipped += 1
            continue
        try:
            cfg.add_profile(name, prof_data)
            imported += 1
            print(f"  ✓ imported '{name}'")
        except Exception as exc:
            print(f"  ✗ failed to import '{name}': {exc}", file=sys.stderr)
            skipped += 1

    if imported > 0:
        config.save(cfg)
    print(f"\nImported {imported} profile(s), skipped {skipped}.")
    return 0 if imported > 0 else 1
