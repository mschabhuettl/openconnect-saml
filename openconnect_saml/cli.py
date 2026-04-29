#!/usr/bin/env python3

import argparse
import enum
import logging
import os
import sys

import openconnect_saml
from openconnect_saml import __version__, app, config


def _add_connection_args(parser):
    """Add common connection arguments to a parser (used by both legacy and connect)."""
    server_settings = parser.add_argument_group("Server connection")
    server_settings.add_argument(
        "-p",
        "--profile",
        dest="profile_path",
        help="Use a profile from this file or directory",
    )
    server_settings.add_argument(
        "-P",
        "--profile-selector",
        dest="use_profile_selector",
        help="Always display profile selector",
        action="store_true",
        default=False,
    )
    server_settings.add_argument("--proxy", help="Use a proxy server")
    server_settings.add_argument(
        "-s",
        "--server",
        help="VPN server to connect to.",
    )

    auth_settings = parser.add_argument_group(
        "Authentication",
        "Used for the same purpose as in OpenConnect.",
    )
    auth_settings.add_argument(
        "--authgroup",
        help="Set to the required authentication login selection",
        default="",
    )
    auth_settings.add_argument(
        "-g",
        "--usergroup",
        help="Override usergroup setting from --server argument",
        default="",
    )
    auth_settings.add_argument(
        "--authenticate",
        help="Authenticate only. Output formatting: {%(choices)s}",
        choices=["shell", "json"],
        const="shell",
        metavar="OUTPUT-FORMAT",
        nargs="?",
        default=False,
    )

    parser.add_argument(
        "--headless",
        help="Run without a browser (no GUI required).",
        action="store_true",
        default=False,
    )
    parser.add_argument(
        "--browser",
        help="Browser backend: 'qt', 'chrome', or 'headless'.",
        choices=["qt", "chrome", "headless"],
        default=None,
    )
    parser.add_argument(
        "--browser-display-mode",
        help="Controls browser window visibility.",
        choices=["shown", "hidden"],
        metavar="DISPLAY-MODE",
        nargs="?",
        default="shown",
    )
    parser.add_argument("--on-connect", help="Command to run after VPN connects", default="")
    parser.add_argument("--on-disconnect", help="Command to run when disconnecting", default="")
    parser.add_argument(
        "--ac-version", help="AnyConnect Version (default: %(default)s)", default="4.7.00136"
    )
    parser.add_argument(
        "-l",
        "--log-level",
        type=LogLevel.parse,
        choices=LogLevel.choices(),
        default=LogLevel.INFO,
    )
    parser.add_argument(
        "openconnect_args",
        help="Arguments passed to openconnect",
        action=StoreOpenConnectArgs,
        nargs=argparse.REMAINDER,
    )

    credentials_group = parser.add_argument_group("Credentials for automatic login")
    credentials_group.add_argument(
        "-u", "--user", help="Authenticate as the given user", default=None
    )
    credentials_group.add_argument(
        "--reset-credentials",
        dest="reset_credentials",
        help="Delete saved credentials from keyring and exit",
        action="store_true",
        default=False,
    )

    totp_group = parser.add_argument_group("TOTP provider options")
    totp_group.add_argument(
        "--totp-source",
        dest="totp_source",
        choices=["local", "2fauth", "bitwarden", "1password", "pass", "none"],
        default=None,
        help="TOTP provider, or 'none' to skip the TOTP prompt entirely",
    )
    totp_group.add_argument(
        "--no-totp",
        dest="no_totp",
        action="store_true",
        default=False,
        help="Don't prompt for a TOTP secret (equivalent to --totp-source none)",
    )
    totp_group.add_argument("--2fauth-url", dest="twofauth_url", default=None)
    totp_group.add_argument("--2fauth-token", dest="twofauth_token", default=None)
    totp_group.add_argument(
        "--2fauth-account-id", dest="twofauth_account_id", type=int, default=None
    )
    totp_group.add_argument(
        "--bw-item-id", dest="bw_item_id", default=None, help="Bitwarden vault item ID for TOTP"
    )
    totp_group.add_argument(
        "--1password-item",
        dest="op_item",
        default=None,
        help="1Password item ID/name that has an OTP field",
    )
    totp_group.add_argument(
        "--1password-vault",
        dest="op_vault",
        default=None,
        help="1Password vault name/UUID (optional)",
    )
    totp_group.add_argument(
        "--1password-account",
        dest="op_account",
        default=None,
        help="1Password account sign-in address (for multi-account setups)",
    )
    totp_group.add_argument(
        "--pass-entry",
        dest="pass_entry",
        default=None,
        help="pass (password-store) entry path for TOTP (requires pass-otp)",
    )

    reconnect_group = parser.add_argument_group("Reconnect options")
    reconnect_group.add_argument(
        "--reconnect",
        help="Automatically reconnect when the VPN connection drops",
        action="store_true",
        default=False,
    )
    reconnect_group.add_argument(
        "--max-retries",
        dest="max_retries",
        type=int,
        default=None,
        help="Maximum reconnection attempts (default: unlimited)",
    )

    route_group = parser.add_argument_group("Split-tunnel routing")
    route_group.add_argument(
        "--route",
        dest="routes",
        action="append",
        default=None,
        help="Include route in VPN tunnel (CIDR). Repeatable.",
    )
    route_group.add_argument(
        "--no-route",
        dest="no_routes",
        action="append",
        default=None,
        help="Exclude route from VPN tunnel (CIDR). Repeatable.",
    )

    notification_group = parser.add_argument_group("Notification options")
    notification_group.add_argument(
        "--notify",
        dest="notify",
        help="Enable desktop notifications for VPN events",
        action="store_true",
        default=False,
    )

    ks_group = parser.add_argument_group("Kill-switch (Linux only)")
    ks_group.add_argument(
        "--kill-switch",
        dest="kill_switch",
        action="store_true",
        default=False,
        help="Enable kill-switch: block all non-VPN traffic until the tunnel is up",
    )
    ks_group.add_argument(
        "--ks-allow-dns",
        dest="ks_allow_dns",
        action="append",
        default=None,
        help="DNS resolver IP to allow through the kill-switch (repeatable)",
    )
    ks_group.add_argument(
        "--ks-allow-lan",
        dest="ks_allow_lan",
        action="store_true",
        default=False,
        help="Allow RFC1918 LAN traffic through the kill-switch",
    )
    ks_group.add_argument(
        "--ks-no-ipv6",
        dest="ks_no_ipv6",
        action="store_true",
        default=False,
        help="Don't install ip6tables kill-switch rules",
    )
    ks_group.add_argument(
        "--ks-port",
        dest="ks_port",
        type=int,
        default=443,
        help="VPN server port to allowlist (default: 443)",
    )
    ks_group.add_argument(
        "--ks-sudo",
        dest="ks_sudo",
        default=None,
        help="Privilege-escalation tool for iptables (default: autodetect sudo/doas)",
    )

    connection_group = parser.add_argument_group("Connection options")
    connection_group.add_argument("--no-sudo", dest="no_sudo", action="store_true", default=False)
    connection_group.add_argument("--csd-wrapper", dest="csd_wrapper", default=None)
    connection_group.add_argument(
        "--ssl-legacy", dest="ssl_legacy", action="store_true", default=False
    )
    connection_group.add_argument("--timeout", dest="timeout", type=int, default=None)
    connection_group.add_argument(
        "--no-history",
        dest="no_history",
        action="store_true",
        default=False,
        help="Don't log this session to ~/.local/state/openconnect-saml/history.jsonl",
    )

    ui_group = parser.add_argument_group("UI options")
    ui_group.add_argument("--window-size", dest="window_size", default=None)
    ui_group.add_argument("--useragent", dest="useragent", default=None)
    return parser


def _add_global_args(parser):
    """Global flags shared by every subcommand and the legacy parser."""
    parser.add_argument(
        "--config",
        dest="config_file",
        metavar="FILE",
        default=None,
        help="Path to config.toml (overrides XDG default and $OPENCONNECT_SAML_CONFIG)",
    )


def create_argparser():
    """Create the main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml", description=openconnect_saml.__description__
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    _add_global_args(parser)

    subparsers = parser.add_subparsers(dest="command")

    # connect
    connect_parser = subparsers.add_parser("connect", help="Connect to a VPN profile or server")
    connect_parser.add_argument(
        "profile_name", nargs="?", default=None, help="Name of a saved profile"
    )
    _add_connection_args(connect_parser)

    # profiles
    profiles_parser = subparsers.add_parser("profiles", help="Manage VPN profiles")
    profiles_sub = profiles_parser.add_subparsers(dest="profiles_action")
    profiles_sub.add_parser("list", help="List all profiles")

    add_parser = profiles_sub.add_parser("add", help="Add a new profile")
    add_parser.add_argument("profile_name")
    add_parser.add_argument("--server")
    add_parser.add_argument("--user-group", default="")
    add_parser.add_argument("--display-name", default="")
    add_parser.add_argument("-u", "--user", default=None)
    add_parser.add_argument(
        "--totp-source",
        default=None,
        choices=["local", "2fauth", "bitwarden", "1password", "pass", "none"],
    )

    remove_parser = profiles_sub.add_parser("remove", help="Remove a profile")
    remove_parser.add_argument("profile_name")

    rename_parser = profiles_sub.add_parser("rename", help="Rename a profile")
    rename_parser.add_argument("profile_name")
    rename_parser.add_argument("new_name")

    show_parser = profiles_sub.add_parser("show", help="Show a single profile (redacted)")
    show_parser.add_argument("profile_name")
    show_parser.add_argument("--json", action="store_true", default=False)

    export_parser = profiles_sub.add_parser(
        "export", help="Export profiles as JSON or NetworkManager .nmconnection (secrets redacted)"
    )
    export_parser.add_argument(
        "profile_name", nargs="?", default=None, help="Profile to export (all if omitted)"
    )
    export_parser.add_argument("--file", "-o", default=None, help="Output file (default: stdout)")
    export_parser.add_argument(
        "--format",
        "-f",
        choices=["json", "nmconnection"],
        default="json",
        help="Export format (default: json). 'nmconnection' produces a NetworkManager "
        "VPN profile compatible with the Ubuntu/GNOME VPN UI.",
    )

    import_parser = profiles_sub.add_parser("import", help="Import profiles from JSON")
    import_parser.add_argument("file", help="Input file (or '-' for stdin)")
    import_parser.add_argument(
        "--as", dest="as_name", default=None, help="Import under a different name"
    )
    import_parser.add_argument(
        "--force", action="store_true", default=False, help="Overwrite existing profiles"
    )

    migrate_parser = profiles_sub.add_parser(
        "migrate", help="Apply schema fix-ups to the active config (idempotent, dry-run by default)"
    )
    migrate_parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Persist changes (default: dry-run)",
    )

    # status
    status_parser = subparsers.add_parser("status", help="Show VPN connection status")
    status_parser.add_argument("--watch", "-w", action="store_true", default=False)
    status_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output status as JSON (suitable for monitoring scripts)",
    )

    # completion
    completion_parser = subparsers.add_parser("completion", help="Generate shell completions")
    completion_parser.add_argument(
        "shell_type", choices=["bash", "zsh", "fish", "install", "_profiles"]
    )

    # setup
    subparsers.add_parser("setup", help="Interactive configuration wizard")

    # service
    subparsers.add_parser("service", help="Manage systemd VPN service", add_help=False)

    # gui
    subparsers.add_parser("gui", help="Open a Tk GUI for saved profiles")

    # tui
    subparsers.add_parser("tui", help="Interactive terminal UI (rich-based)")

    # config
    config_parser = subparsers.add_parser("config", help="Inspect config file")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("path", help="Print path to config file")
    config_show = config_sub.add_parser("show", help="Show config (secrets redacted)")
    config_show.add_argument("--json", action="store_true", default=False)
    config_sub.add_parser("validate", help="Validate config file")
    config_sub.add_parser("edit", help="Open config file in $EDITOR")

    # doctor
    doctor_parser = subparsers.add_parser("doctor", help="Run diagnostic checks")
    doctor_parser.add_argument(
        "-s", "--server", default=None, help="Optional: test DNS + TCP to this server"
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit results as JSON (machine-readable)",
    )

    # history
    history_parser = subparsers.add_parser("history", help="Show connection history")
    history_sub = history_parser.add_subparsers(dest="history_action")
    history_show = history_sub.add_parser("show", help="Show connection log")
    history_show.add_argument("--limit", "-n", type=int, default=None)
    history_show.add_argument("--json", action="store_true", default=False)
    history_sub.add_parser("clear", help="Clear the history log")
    history_sub.add_parser("path", help="Print path to history file")
    history_stats = history_sub.add_parser("stats", help="Show aggregated connection statistics")
    history_stats.add_argument("--json", action="store_true", default=False)
    history_parser.add_argument("--limit", "-n", type=int, default=None)
    history_parser.add_argument("--json", action="store_true", default=False)

    # killswitch
    ks_parser = subparsers.add_parser(
        "killswitch", help="Manage the traffic kill-switch (Linux only)"
    )
    ks_sub = ks_parser.add_subparsers(dest="killswitch_action")
    ks_enable = ks_sub.add_parser("enable", help="Enable kill-switch")
    ks_enable.add_argument("-s", "--server", required=True, help="VPN server to allowlist")
    ks_enable.add_argument("--ks-port", type=int, default=443)
    ks_enable.add_argument("--ks-allow-dns", action="append", default=None)
    ks_enable.add_argument("--ks-allow-lan", action="store_true", default=False)
    ks_enable.add_argument("--ks-no-ipv6", action="store_true", default=False)
    ks_enable.add_argument("--ks-sudo", default=None)
    ks_sub.add_parser("disable", help="Disable kill-switch")
    ks_sub.add_parser("status", help="Show kill-switch status")

    return parser


def create_legacy_argparser():
    """Legacy (no-subcommand) parser for backwards compatibility."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml", description=openconnect_saml.__description__
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    _add_global_args(parser)
    _add_connection_args(parser)
    return parser


class StoreOpenConnectArgs(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if "--" in values:
            values.remove("--")
        setattr(namespace, self.dest, values)


class LogLevel(enum.IntEnum):
    ERROR = logging.ERROR
    WARNING = logging.WARNING
    INFO = logging.INFO
    DEBUG = logging.DEBUG

    def __str__(self):
        return self.name

    @classmethod
    def parse(cls, name):
        try:
            level = cls.__members__[name.upper()]
        except KeyError:
            print(f"unknown loglevel '{name}', setting to INFO", file=sys.stderr)
            level = logging.INFO
        return level

    @classmethod
    def choices(cls):
        return cls.__members__.values()


def create_service_argparser():
    """Parser for the 'service' subcommand."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml service",
        description="Manage systemd service for persistent VPN connections",
    )
    subparsers = parser.add_subparsers(dest="service_action", required=True)

    install_p = subparsers.add_parser("install", help="Install systemd unit")
    install_p.add_argument("-s", "--server", required=True)
    install_p.add_argument("-u", "--user")
    install_p.add_argument("--browser", choices=["headless", "chrome", "qt"], default="headless")
    install_p.add_argument("--max-retries", type=int, default=None)

    uninstall_p = subparsers.add_parser("uninstall", help="Remove systemd unit")
    uninstall_p.add_argument("-s", "--server", required=True)

    start_p = subparsers.add_parser("start", help="Start VPN service")
    start_p.add_argument("-s", "--server", required=True)

    stop_p = subparsers.add_parser("stop", help="Stop VPN service")
    stop_p.add_argument("-s", "--server", required=True)

    status_p = subparsers.add_parser("status", help="Show service status")
    status_p.add_argument("-s", "--server", default=None)

    logs_p = subparsers.add_parser("logs", help="Show service logs")
    logs_p.add_argument("-s", "--server", default=None)
    logs_p.add_argument("-f", "--follow", action="store_true")

    return parser


def _recover_connect_options_from_remainder(args):
    """Recover openconnect-saml options swallowed after `connect PROFILE`.

    argparse.REMAINDER is kept for backwards-compatible openconnect passthrough,
    but it also captures options placed after the profile name.  This makes
    `openconnect-saml connect work --browser chrome` silently use Qt (#21).
    Pull known local options back out and leave the rest for openconnect.
    """
    remainder = list(getattr(args, "openconnect_args", []) or [])
    if not remainder:
        return

    cleaned = []
    i = 0
    while i < len(remainder):
        token = remainder[i]
        if (
            token == "--browser"
            and i + 1 < len(remainder)
            and remainder[i + 1] in {"qt", "chrome", "headless"}
        ):
            args.browser = remainder[i + 1]
            if args.browser == "headless":
                args.headless = True
            i += 2
            continue
        if token.startswith("--browser="):
            value = token.split("=", 1)[1]
            if value in {"qt", "chrome", "headless"}:
                args.browser = value
                if value == "headless":
                    args.headless = True
                i += 1
                continue
        if token == "--headless":
            args.headless = True
            args.browser = "headless"
            i += 1
            continue
        cleaned.append(token)
        i += 1
    args.openconnect_args = cleaned


def _handle_profiles_command(args):
    from openconnect_saml.profiles import handle_profiles_command

    return handle_profiles_command(args)


def _handle_status_command(args):
    from openconnect_saml.tui import handle_status_command

    return handle_status_command(args)


def _handle_completion_command(args):
    from openconnect_saml.completion import handle_completion_command

    return handle_completion_command(args)


def _handle_setup_command():
    from openconnect_saml.setup_wizard import run_setup_wizard

    return run_setup_wizard()


def _handle_config_command(args):
    from openconnect_saml.config_cmd import handle_config_command

    return handle_config_command(args)


def _handle_doctor_command(args):
    from openconnect_saml.doctor import handle_doctor_command

    return handle_doctor_command(args)


def _handle_history_command(args):
    from openconnect_saml.history import handle_history_command

    return handle_history_command(args)


def _handle_killswitch_command(args):
    from openconnect_saml.killswitch import handle_killswitch_command

    return handle_killswitch_command(args)


def _handle_gui_command():
    from openconnect_saml.gui import main as gui_main

    return gui_main()


def _handle_tui_command():
    from openconnect_saml.interactive_tui import handle_tui_command

    return handle_tui_command()


def _handle_connect(args, parser):
    """Handle the 'connect' subcommand or legacy invocation."""
    _recover_connect_options_from_remainder(args)
    if args.browser and args.browser == "headless":
        args.headless = True

    if (getattr(args, "profile_path", None) or getattr(args, "use_profile_selector", False)) and (
        args.server or args.usergroup
    ):
        parser.error("--profile/--profile-selector and --server/--usergroup are mutually exclusive")

    profile_name = getattr(args, "profile_name", None)
    if profile_name:
        cfg = config.load()
        prof = cfg.get_profile(profile_name)
        if not prof:
            print(f"Error: profile '{profile_name}' not found.", file=sys.stderr)
            print("Available profiles:", file=sys.stderr)
            for name, _ in cfg.list_profiles():
                print(f"  - {name}", file=sys.stderr)
            return 1
        if not args.server:
            args.server = prof.server
        if not args.usergroup and prof.user_group:
            args.usergroup = prof.user_group
        if not args.authgroup and prof.name:
            args.authgroup = prof.name
        if prof.credentials:
            if not args.user and prof.credentials.username:
                args.user = prof.credentials.username
            if not getattr(args, "totp_source", None) and prof.credentials.totp_source:
                args.totp_source = prof.credentials.totp_source

    if (
        not getattr(args, "profile_path", None)
        and not args.server
        and not config.load().default_profile
    ):
        if os.path.exists("/opt/cisco/anyconnect/profile"):
            args.profile_path = "/opt/cisco/anyconnect/profile"
        else:
            parser.error(
                "No AnyConnect profile can be found. "
                "One of --profile, --server, or a saved profile name is required."
            )

    if getattr(args, "use_profile_selector", False) and not getattr(args, "profile_path", None):
        parser.error("No AnyConnect profile can be found. --profile argument is required.")

    return app.run(args)


def _is_legacy_invocation(argv):
    """Check if the invocation uses legacy (no subcommand) style."""
    if not argv:
        return True
    known_subcommands = {
        "connect",
        "profiles",
        "status",
        "completion",
        "service",
        "setup",
        "config",
        "doctor",
        "history",
        "killswitch",
        "gui",
        "tui",
    }
    first = argv[0]
    return first.startswith("-") or first not in known_subcommands


def _apply_config_override(args):
    """If --config FILE was given, propagate it via OPENCONNECT_SAML_CONFIG.

    The env var is read by ``config.load`` / ``config.save`` so every callsite
    picks it up without explicit threading.
    """
    config_file = getattr(args, "config_file", None)
    if config_file:
        from openconnect_saml.config import CONFIG_ENV_VAR

        os.environ[CONFIG_ENV_VAR] = config_file


def main():
    argv = sys.argv[1:]

    # 'service' has its own parser because it conflicts with the main one
    if len(argv) > 0 and argv[0] == "service":
        from openconnect_saml.service import handle_service_command

        service_parser = create_service_argparser()
        args = service_parser.parse_args(argv[1:])
        return handle_service_command(args)

    if not _is_legacy_invocation(argv):
        parser = create_argparser()
        args = parser.parse_args(argv)
        _apply_config_override(args)

        if args.command == "connect":
            return _handle_connect(args, parser)
        if args.command == "profiles":
            return _handle_profiles_command(args)
        if args.command == "status":
            return _handle_status_command(args)
        if args.command == "completion":
            return _handle_completion_command(args)
        if args.command == "setup":
            return _handle_setup_command()
        if args.command == "config":
            return _handle_config_command(args)
        if args.command == "doctor":
            return _handle_doctor_command(args)
        if args.command == "history":
            return _handle_history_command(args)
        if args.command == "killswitch":
            return _handle_killswitch_command(args)
        if args.command == "gui":
            return _handle_gui_command()
        if args.command == "tui":
            return _handle_tui_command()

        parser.print_help()
        return 0

    # Legacy mode: no subcommand
    parser = create_legacy_argparser()
    args = parser.parse_args(argv)
    _apply_config_override(args)
    args.profile_name = None
    return _handle_connect(args, parser)


if __name__ == "__main__":
    sys.exit(main())
