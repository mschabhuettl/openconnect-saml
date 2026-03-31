"""Multi-profile management for openconnect-saml.

Provides CLI handlers for listing, adding, and removing named VPN profiles
from the configuration file.
"""

import sys

from openconnect_saml import config


def handle_profiles_command(args):
    """Dispatch profiles subcommands."""
    action = getattr(args, "profiles_action", None)

    if action == "add":
        return _add_profile(args)
    elif action == "remove":
        return _remove_profile(args)
    else:
        # Default: list profiles
        return _list_profiles()


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


def _add_profile(args):
    """Add or update a named profile."""
    cfg = config.load()
    name = args.profile_name

    server = getattr(args, "server", None)
    if not server:
        # Interactive mode
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

    existed = name in cfg.profiles
    cfg.add_profile(name, profile_data)
    config.save(cfg)

    action = "Updated" if existed else "Added"
    print(f"{action} profile '{name}' → {server}")
    return 0


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
