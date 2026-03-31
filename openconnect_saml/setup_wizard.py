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
from openconnect_saml.config import BitwardenConfig, TwoFAuthConfig

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


def run_setup_wizard() -> int:
    """Run the interactive setup wizard.

    Returns
    -------
    int
        Exit code (0 on success, 1 on abort).
    """
    print()
    print("🔧 openconnect-saml Setup Wizard")
    print("=" * 40)
    print()

    # 1. Server URL
    server = _prompt("VPN server URL (e.g. vpn.example.com)", required=True)

    # 2. Username
    username = _prompt("Username (e.g. user@domain.com)")

    # 3. TOTP source
    totp_source = _prompt_choice(
        "TOTP source",
        ["local", "2fauth", "bitwarden", "none"],
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
        if totp_source and totp_source != "none":
            cred_data["totp_source"] = totp_source

    profile_data = {
        "server": server,
        "user_group": "",
        "name": profile_name,
    }
    if cred_data:
        profile_data["credentials"] = cred_data

    cfg.add_profile(profile_name, profile_data)

    # Set as default if first profile or user wants it
    if not cfg.default_profile or _prompt_yes_no("Set as default profile?", default=True):
        cfg.default_profile = config.HostProfile(server, "", profile_name)
        if username:
            cfg.credentials = config.Credentials(username)
            if totp_source and totp_source != "none":
                cfg.credentials.totp_source = totp_source

    # Save 2FAuth config
    if twofauth_cfg:
        cfg.twofauth = twofauth_cfg

    # Save Bitwarden config
    if bitwarden_cfg:
        cfg.bitwarden = bitwarden_cfg

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
