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
        help="VPN server to connect to. The following forms are accepted: "
        "vpn.server.com, vpn.server.com/usergroup, "
        "https://vpn.server.com, https.vpn.server.com.usergroup",
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
    parser.add_argument(
        "--on-connect",
        help="Command/script to run after VPN connection is established",
        default="",
    )
    parser.add_argument(
        "--on-disconnect",
        help="Command to run when disconnecting from VPN server",
        default="",
    )
    parser.add_argument(
        "--ac-version",
        help="AnyConnect Version (default: %(default)s)",
        default="4.7.00136",
    )
    parser.add_argument(
        "-l",
        "--log-level",
        help="",
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
        choices=["local", "2fauth", "bitwarden"],
        default=None,
        help="TOTP provider: 'local', '2fauth', or 'bitwarden'",
    )
    totp_group.add_argument(
        "--2fauth-url",
        dest="twofauth_url",
        default=None,
        help="2FAuth instance URL",
    )
    totp_group.add_argument(
        "--2fauth-token",
        dest="twofauth_token",
        default=None,
        help="2FAuth Personal Access Token",
    )
    totp_group.add_argument(
        "--2fauth-account-id",
        dest="twofauth_account_id",
        type=int,
        default=None,
        help="2FAuth account ID",
    )
    totp_group.add_argument(
        "--bw-item-id",
        dest="bw_item_id",
        default=None,
        help="Bitwarden vault item ID for TOTP",
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
        help="Include route in VPN tunnel (CIDR, e.g. 10.0.0.0/8). Repeatable.",
    )
    route_group.add_argument(
        "--no-route",
        dest="no_routes",
        action="append",
        default=None,
        help="Exclude route from VPN tunnel (CIDR, e.g. 192.168.0.0/16). Repeatable.",
    )

    notification_group = parser.add_argument_group("Notification options")
    notification_group.add_argument(
        "--notify",
        dest="notify",
        help="Enable desktop notifications for VPN events",
        action="store_true",
        default=False,
    )

    connection_group = parser.add_argument_group("Connection options")
    connection_group.add_argument(
        "--no-sudo",
        dest="no_sudo",
        help="Do not use sudo/doas to run openconnect",
        action="store_true",
        default=False,
    )
    connection_group.add_argument(
        "--csd-wrapper",
        dest="csd_wrapper",
        help="Path to CSD hostscan wrapper script",
        default=None,
    )
    connection_group.add_argument(
        "--ssl-legacy",
        dest="ssl_legacy",
        help="Enable SSL legacy renegotiation",
        action="store_true",
        default=False,
    )
    connection_group.add_argument(
        "--allowed-domain",
        dest="allowed_domain",
        help="Whitelist domain for headless auth redirects (e.g. login.microsoft.com). "
        "Prevents credential leaking to untrusted domains.",
        default=None,
    )
    connection_group.add_argument(
        "--timeout",
        dest="timeout",
        help="HTTP request timeout in seconds (default: 30)",
        type=int,
        default=None,
    )

    ui_group = parser.add_argument_group("UI options")
    ui_group.add_argument(
        "--window-size",
        dest="window_size",
        help="Browser window size as WIDTHxHEIGHT (default: 800x600)",
        default=None,
    )
    ui_group.add_argument(
        "--useragent",
        dest="useragent",
        help="Custom User-Agent string for OpenConnect (default: AnyConnect Linux_64/x.x.x)",
        default=None,
    )
    return parser


def create_argparser():
    """Create the main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml", description=openconnect_saml.__description__
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    # 'connect' subcommand
    connect_parser = subparsers.add_parser("connect", help="Connect to a VPN profile or server")
    connect_parser.add_argument(
        "profile_name",
        nargs="?",
        default=None,
        help="Name of a saved profile to connect to",
    )
    _add_connection_args(connect_parser)

    # 'profiles' subcommand
    profiles_parser = subparsers.add_parser("profiles", help="Manage VPN profiles")
    profiles_sub = profiles_parser.add_subparsers(dest="profiles_action")
    profiles_sub.add_parser("list", help="List all profiles")

    add_parser = profiles_sub.add_parser("add", help="Add a new profile")
    add_parser.add_argument("profile_name", help="Profile name")
    add_parser.add_argument("--server", required=False, help="VPN server address")
    add_parser.add_argument("--user-group", default="", help="User group")
    add_parser.add_argument("--display-name", default="", help="Display name for the profile")
    add_parser.add_argument("-u", "--user", default=None, help="Username")
    add_parser.add_argument(
        "--totp-source", default=None, choices=["local", "2fauth"], help="TOTP source"
    )

    remove_parser = profiles_sub.add_parser("remove", help="Remove a profile")
    remove_parser.add_argument("profile_name", help="Profile name to remove")

    # 'status' subcommand
    status_parser = subparsers.add_parser("status", help="Show VPN connection status")
    status_parser.add_argument(
        "--watch",
        "-w",
        action="store_true",
        default=False,
        help="Live-update status every 2 seconds",
    )

    # 'completion' subcommand
    completion_parser = subparsers.add_parser("completion", help="Generate shell completions")
    completion_parser.add_argument(
        "shell_type",
        choices=["bash", "zsh", "fish", "install", "_profiles"],
        help="Shell type or 'install' for auto-installation",
    )

    # 'setup' subcommand (interactive config wizard)
    subparsers.add_parser("setup", help="Interactive configuration wizard")

    # 'service' subcommand (for backwards compat, handled separately)
    subparsers.add_parser("service", help="Manage systemd VPN service", add_help=False)

    return parser


def create_legacy_argparser():
    """Create a legacy-compatible parser (no subcommands) for backwards compatibility."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml", description=openconnect_saml.__description__
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
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
    """Create a separate parser for the 'service' subcommand."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml service",
        description="Manage systemd service for persistent VPN connections",
    )
    subparsers = parser.add_subparsers(dest="service_action", required=True)

    install_p = subparsers.add_parser("install", help="Install systemd unit")
    install_p.add_argument("-s", "--server", required=True, help="VPN server address")
    install_p.add_argument("-u", "--user", help="Username for authentication")
    install_p.add_argument(
        "--browser",
        choices=["headless", "chrome", "qt"],
        default="headless",
        help="Browser backend for the service (default: headless)",
    )
    install_p.add_argument("--max-retries", type=int, default=None, help="Max reconnection retries")

    uninstall_p = subparsers.add_parser("uninstall", help="Remove systemd unit")
    uninstall_p.add_argument("-s", "--server", required=True, help="VPN server address")

    start_p = subparsers.add_parser("start", help="Start VPN service")
    start_p.add_argument("-s", "--server", required=True, help="VPN server address")

    stop_p = subparsers.add_parser("stop", help="Stop VPN service")
    stop_p.add_argument("-s", "--server", required=True, help="VPN server address")

    status_p = subparsers.add_parser("status", help="Show service status")
    status_p.add_argument("-s", "--server", default=None, help="VPN server address")

    logs_p = subparsers.add_parser("logs", help="Show service logs")
    logs_p.add_argument("-s", "--server", default=None, help="VPN server address")
    logs_p.add_argument("-f", "--follow", action="store_true", help="Follow log output")

    return parser


def _handle_profiles_command(args):
    """Handle the 'profiles' subcommand."""
    from openconnect_saml.profiles import handle_profiles_command

    return handle_profiles_command(args)


def _handle_status_command(args):
    """Handle the 'status' subcommand."""
    from openconnect_saml.tui import handle_status_command

    return handle_status_command(args)


def _handle_completion_command(args):
    """Handle the 'completion' subcommand."""
    from openconnect_saml.completion import handle_completion_command

    return handle_completion_command(args)


def _handle_setup_command():
    """Handle the 'setup' subcommand (interactive wizard)."""
    from openconnect_saml.setup_wizard import run_setup_wizard

    return run_setup_wizard()


def _handle_connect(args, parser):
    """Handle the 'connect' subcommand or legacy invocation."""
    # --browser flag overrides --headless
    if args.browser and args.browser == "headless":
        args.headless = True

    if (getattr(args, "profile_path", None) or getattr(args, "use_profile_selector", False)) and (
        args.server or args.usergroup
    ):
        parser.error("--profile/--profile-selector and --server/--usergroup are mutually exclusive")

    # If a profile_name is given, resolve it from config
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
        # Apply profile settings (--server flag overrides profile server)
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
                "No AnyConnect profile can be found. One of --profile, --server, or a saved profile name is required."
            )

    if getattr(args, "use_profile_selector", False) and not getattr(args, "profile_path", None):
        parser.error("No AnyConnect profile can be found. --profile argument is required.")

    return app.run(args)


def _is_legacy_invocation(argv):
    """Check if the invocation uses legacy (no subcommand) style."""
    if not argv:
        return True
    known_subcommands = {"connect", "profiles", "status", "completion", "service", "setup"}
    first = argv[0]
    # If the first arg starts with - or is not a subcommand, it's legacy
    return first.startswith("-") or first not in known_subcommands


def main():
    argv = sys.argv[1:]

    # Check for 'service' subcommand before main argparse
    if len(argv) > 0 and argv[0] == "service":
        from openconnect_saml.service import handle_service_command

        service_parser = create_service_argparser()
        args = service_parser.parse_args(argv[1:])
        return handle_service_command(args)

    # Check for known subcommands
    if not _is_legacy_invocation(argv):
        parser = create_argparser()
        args = parser.parse_args(argv)

        if args.command == "connect":
            return _handle_connect(args, parser)
        elif args.command == "profiles":
            return _handle_profiles_command(args)
        elif args.command == "status":
            return _handle_status_command(args)
        elif args.command == "completion":
            return _handle_completion_command(args)
        elif args.command == "setup":
            return _handle_setup_command()
        else:
            parser.print_help()
            return 0
    else:
        # Legacy mode: no subcommand
        parser = create_legacy_argparser()
        args = parser.parse_args(argv)
        # Set profile_name to None for legacy compat
        args.profile_name = None
        return _handle_connect(args, parser)


if __name__ == "__main__":
    sys.exit(main())
