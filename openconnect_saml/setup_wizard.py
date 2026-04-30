"""Interactive configuration wizard for openconnect-saml.

Guides the user through setting up a VPN profile interactively:
server URL, username, TOTP source, browser mode, auto-reconnect,
and profile name. Uses prompt_toolkit for input.

Run via: ``openconnect-saml setup``
"""

from __future__ import annotations

import sys

import structlog

from openconnect_saml import config
from openconnect_saml.config import (
    BitwardenConfig,
    OnePasswordConfig,
    PassConfig,
    TwoFAuthConfig,
)

logger = structlog.get_logger()


def _prompt(message: str, default: str = "", required: bool = False) -> str:
    """Prompt for input with optional default."""
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{message}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)
    if not value and default:
        return default
    if required and not value:
        print("  This field is required.")
        return _prompt(message, default, required)
    return value


def _prompt_choice(message: str, choices: list[str], default: str = "") -> str:
    """Prompt for a choice from a list."""
    choices_str = "/".join(choices)
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{message} ({choices_str}){suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)
    if not value and default:
        return default
    if value not in choices:
        print(f"  Please choose one of: {choices_str}")
        return _prompt_choice(message, choices, default)
    return value


def _prompt_yes_no(message: str, default: bool = False) -> bool:
    """Prompt for a yes/no answer."""
    suffix = " [Y/n]" if default else " [y/N]"
    try:
        value = input(f"{message}{suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)
    if not value:
        return default
    return value in ("y", "yes", "ja", "j")


def _scan_anyconnect_xml_dirs() -> list[str]:
    """Look for Cisco AnyConnect ``.xml`` profile files in the standard
    locations. Returns a list of absolute paths.
    """
    from pathlib import Path

    candidates = [
        "/opt/cisco/anyconnect/profile",
        "/opt/cisco/secureclient/anyconnect/profile",
        str(Path.home() / ".cisco/profile"),
    ]
    found: list[str] = []
    for d in candidates:
        p = Path(d)
        if p.is_dir():
            found.extend(str(x) for x in sorted(p.glob("*.xml")))
    return found


def _maybe_offer_xml_import() -> bool:
    """If a Cisco AnyConnect profile dir exists, offer to import it.

    Returns True if the user chose to import (and the wizard should exit).
    """
    files = _scan_anyconnect_xml_dirs()
    if not files:
        return False
    print()
    print("Found existing AnyConnect XML profile(s):")
    for f in files:
        print(f"  • {f}")
    print()
    if not _prompt_yes_no("Import these into openconnect-saml profiles?", default=True):
        return False

    from openconnect_saml import config as _config
    from openconnect_saml.profile import _get_profiles_from_one_file

    cfg = _config.load()
    imported = 0
    for path_str in files:
        from pathlib import Path as _Path

        try:
            host_profiles = _get_profiles_from_one_file(_Path(path_str))
        except Exception as exc:  # noqa: BLE001
            print(f"  ! could not parse {path_str}: {exc}")
            continue
        for hp in host_profiles:
            raw = (hp.name or hp.address or "").strip()
            if not raw:
                continue
            key = raw.replace(" ", "_")
            if key in cfg.profiles:
                continue
            cfg.add_profile(
                key,
                {"server": hp.address, "user_group": hp.user_group or "", "name": raw},
            )
            print(f"  ✓ imported '{key}' → {hp.address}")
            imported += 1
    if imported:
        _config.save(cfg)
        print(f"\n✅ Imported {imported} profile(s).")
        return True
    print("Nothing new to import.")
    return False


def run_setup_wizard(advanced: bool = False) -> int:
    """Run the interactive setup wizard.

    Parameters
    ----------
    advanced
        When True, additionally asks for per-profile overrides (cert,
        on_connect / on_disconnect hooks, kill-switch). When False
        (default) keeps the wizard short and beginner-friendly.

    Returns
    -------
    int
        Exit code (0 on success, 1 on abort).
    """
    print()
    print("🔧 openconnect-saml Setup Wizard")
    print("=" * 40)
    print()

    if _maybe_offer_xml_import():
        # Imported — that's a sufficient setup; remind user how to connect.
        print()
        print("Connect with: openconnect-saml connect <profile-name>")
        return 0

    # 1. Server URL
    server = _prompt("VPN server URL (e.g. vpn.example.com)", required=True)

    # 2. Username
    username = _prompt("Username (e.g. user@domain.com)")

    # 3. TOTP source
    totp_source = _prompt_choice(
        "TOTP source",
        ["local", "2fauth", "bitwarden", "1password", "pass", "none"],
        default="local",
    )

    # 4. 2FAuth config
    twofauth_cfg = None
    if totp_source == "2fauth":
        print()
        print("  2FAuth Configuration:")
        twofauth_url = _prompt("  2FAuth URL (e.g. https://2fauth.example.com)", required=True)
        twofauth_token = _prompt("  2FAuth Personal Access Token", required=True)
        twofauth_account_id = _prompt("  2FAuth Account ID", required=True)
        try:
            twofauth_cfg = TwoFAuthConfig(
                url=twofauth_url,
                token=twofauth_token,
                account_id=int(twofauth_account_id),
            )
        except ValueError:
            print("  Error: Account ID must be a number.")
            return 1

    # 4b. Bitwarden config
    bitwarden_cfg = None
    if totp_source == "bitwarden":
        print()
        print("  Bitwarden Configuration:")
        bw_item_id = _prompt("  Bitwarden item ID (UUID)", required=True)
        bitwarden_cfg = BitwardenConfig(item_id=bw_item_id)

    # 4c. 1Password config
    onepassword_cfg = None
    if totp_source == "1password":
        print()
        print("  1Password Configuration (requires the 'op' CLI):")
        op_item = _prompt("  1Password item name or UUID", required=True)
        op_vault = _prompt("  Vault (optional)")
        op_account = _prompt("  Account sign-in URL (optional, for multi-account)")
        onepassword_cfg = OnePasswordConfig(item=op_item, vault=op_vault, account=op_account)

    # 4d. pass (password-store) config
    pass_cfg = None
    if totp_source == "pass":
        print()
        print("  pass Configuration (requires pass-otp):")
        pass_entry = _prompt("  pass entry path (e.g. work/vpn-totp)", required=True)
        pass_cfg = PassConfig(entry=pass_entry)

    # 5. Browser mode
    browser_mode = _prompt_choice(
        "Browser mode",
        ["headless", "chrome", "qt"],
        default="headless",
    )

    # 6. Auto-reconnect
    auto_reconnect = _prompt_yes_no("Enable auto-reconnect?", default=True)

    # 7. Notifications
    notifications = _prompt_yes_no("Enable desktop notifications?", default=False)

    # 7b. Advanced options (per-profile overrides) — only on --advanced
    cert_path = ""
    cert_key_path = ""
    on_connect_cmd = ""
    on_disconnect_cmd = ""
    enable_killswitch = False
    if advanced:
        print()
        print("  Advanced options (leave blank to skip)")
        cert_path = _prompt("  Client certificate (PEM file path)")
        if cert_path:
            cert_key_path = _prompt("  Private key (PEM file path)", required=True)
        on_connect_cmd = _prompt("  on-connect hook (shell command)")
        on_disconnect_cmd = _prompt("  on-disconnect hook (shell command)")
        enable_killswitch = _prompt_yes_no("  Enable persistent kill-switch?", default=False)

    # 8. Profile name
    profile_name = _prompt("Profile name", default="default", required=True)

    # Summary
    print()
    print("📋 Summary:")
    print(f"  Profile:       {profile_name}")
    print(f"  Server:        {server}")
    print(f"  Username:      {username or '(none)'}")
    print(f"  TOTP source:   {totp_source}")
    print(f"  Browser:       {browser_mode}")
    print(f"  Auto-reconnect: {'yes' if auto_reconnect else 'no'}")
    print(f"  Notifications: {'yes' if notifications else 'no'}")
    print()

    if not _prompt_yes_no("Save this configuration?", default=True):
        print("Aborted.")
        return 1

    # Build and save config
    cfg = config.load()

    # Build profile
    cred_data = None
    if username:
        cred_data = {"username": username}
        if totp_source:
            # Save explicit "none" too so future runs don't re-prompt for TOTP.
            cred_data["totp_source"] = totp_source

    profile_data = {
        "server": server,
        "user_group": "",
        "name": profile_name,
    }
    if cred_data:
        profile_data["credentials"] = cred_data

    # Advanced per-profile fields (--advanced only)
    if advanced:
        if cert_path:
            profile_data["cert"] = cert_path
        if cert_key_path:
            profile_data["cert_key"] = cert_key_path
        if on_connect_cmd:
            profile_data["on_connect"] = on_connect_cmd
        if on_disconnect_cmd:
            profile_data["on_disconnect"] = on_disconnect_cmd
        if enable_killswitch:
            profile_data["kill_switch"] = {"enabled": True}

    cfg.add_profile(profile_name, profile_data)

    # Set as default if first profile or user wants it
    if not cfg.default_profile or _prompt_yes_no("Set as default profile?", default=True):
        cfg.default_profile = config.HostProfile(server, "", profile_name)
        if username:
            cfg.credentials = config.Credentials(username)
            if totp_source:
                cfg.credentials.totp_source = totp_source

    # Save 2FAuth config
    if twofauth_cfg:
        cfg.twofauth = twofauth_cfg

    # Save Bitwarden config
    if bitwarden_cfg:
        cfg.bitwarden = bitwarden_cfg

    # Save 1Password config
    if onepassword_cfg:
        cfg.onepassword = onepassword_cfg

    # Save pass config
    if pass_cfg:
        cfg.pass_ = pass_cfg

    # Notifications
    cfg.notifications = notifications

    config.save(cfg)

    print()
    print("✅ Configuration saved!")
    print()
    print("Connect with:")
    cmd = f"  openconnect-saml connect {profile_name}"
    if browser_mode != "qt":
        cmd += f" --browser {browser_mode}"
    if auto_reconnect:
        cmd += " --reconnect"
    if notifications:
        cmd += " --notify"
    print(cmd)

    return 0
