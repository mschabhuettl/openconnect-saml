#!/usr/bin/env python3

import argparse
import enum
import logging
import os
import sys

import openconnect_saml
from openconnect_saml import __version__, app, config


def create_argparser():
    parser = argparse.ArgumentParser(
        prog="openconnect-saml", description=openconnect_saml.__description__
    )

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
        "Used for the same purpose as in OpenConnect. Refer to OpenConnect's documentation for further information",
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
        help="Authenticate only, and output the information needed to make the connection. Output formatting choices: {%(choices)s}",
        choices=["shell", "json"],
        const="shell",
        metavar="OUTPUT-FORMAT",
        nargs="?",
        default=False,
    )

    parser.add_argument(
        "--headless",
        help="Run without a browser (no GUI required). Uses automatic form-based "
        "authentication or a local callback server for manual browser auth. "
        "Ideal for servers, containers, and SSH sessions.",
        action="store_true",
        default=False,
    )

    parser.add_argument(
        "--browser",
        help="Browser backend to use for SAML authentication. "
        "'qt' uses PyQt6 WebEngine (default), 'chrome' uses Playwright/Chromium, "
        "'headless' is equivalent to --headless. Choices: {%(choices)s}",
        choices=["qt", "chrome", "headless"],
        default=None,
    )

    parser.add_argument(
        "--browser-display-mode",
        help="Controls how the browser window is displayed. 'hidden' mode only works with saved credentials. Choices: {%(choices)s}",
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

    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")

    parser.add_argument(
        "--ac-version",
        help="AnyConnect Version used for authentication and for OpenConnect, defaults to %(default)s",
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
        help="Maximum number of reconnection attempts (default: unlimited)",
    )

    connection_group = parser.add_argument_group("Connection options")
    connection_group.add_argument(
        "--no-sudo",
        dest="no_sudo",
        help="Do not use sudo/doas to run openconnect (for use with --script-tun etc.)",
        action="store_true",
        default=False,
    )
    connection_group.add_argument(
        "--csd-wrapper",
        dest="csd_wrapper",
        help="Path to CSD hostscan wrapper script, passed to openconnect --csd-wrapper",
        default=None,
    )
    connection_group.add_argument(
        "--ssl-legacy",
        dest="ssl_legacy",
        help="Enable SSL legacy renegotiation for servers that require it (#81)",
        action="store_true",
        default=False,
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
        help="Browser window size as WIDTHxHEIGHT (e.g. 1000x800, default: 800x600)",
        default=None,
    )
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

    # install
    install_p = subparsers.add_parser("install", help="Install systemd unit")
    install_p.add_argument("-s", "--server", required=True, help="VPN server address")
    install_p.add_argument("-u", "--user", help="Username for authentication")
    install_p.add_argument(
        "--browser",
        choices=["headless", "chrome", "qt"],
        default="headless",
        help="Browser backend for the service (default: headless)",
    )
    install_p.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help="Max reconnection retries (default: unlimited)",
    )

    # uninstall
    uninstall_p = subparsers.add_parser("uninstall", help="Remove systemd unit")
    uninstall_p.add_argument("-s", "--server", required=True, help="VPN server address")

    # start
    start_p = subparsers.add_parser("start", help="Start VPN service")
    start_p.add_argument("-s", "--server", required=True, help="VPN server address")

    # stop
    stop_p = subparsers.add_parser("stop", help="Stop VPN service")
    stop_p.add_argument("-s", "--server", required=True, help="VPN server address")

    # status
    status_p = subparsers.add_parser("status", help="Show service status")
    status_p.add_argument("-s", "--server", default=None, help="VPN server address (optional)")

    # logs
    logs_p = subparsers.add_parser("logs", help="Show service logs")
    logs_p.add_argument("-s", "--server", default=None, help="VPN server address (optional)")
    logs_p.add_argument("-f", "--follow", action="store_true", help="Follow log output")

    return parser


def main():
    # Check for 'service' subcommand before main argparse
    if len(sys.argv) > 1 and sys.argv[1] == "service":
        from openconnect_saml.service import handle_service_command

        service_parser = create_service_argparser()
        args = service_parser.parse_args(sys.argv[2:])
        return handle_service_command(args)

    parser = create_argparser()
    args = parser.parse_args()

    # --browser flag overrides --headless
    if args.browser and args.browser == "headless":
        args.headless = True
    # chrome and qt are handled in app.py

    if (args.profile_path or args.use_profile_selector) and (args.server or args.usergroup):
        parser.error("--profile/--profile-selector and --server/--usergroup are mutually exclusive")

    if not args.profile_path and not args.server and not config.load().default_profile:
        if os.path.exists("/opt/cisco/anyconnect/profile"):
            args.profile_path = "/opt/cisco/anyconnect/profile"
        else:
            parser.error(
                "No AnyConnect profile can be found. One of --profile or --server arguments required."
            )

    if args.use_profile_selector and not args.profile_path:
        parser.error("No AnyConnect profile can be found. --profile argument is required.")

    return app.run(args)


if __name__ == "__main__":
    sys.exit(main())
