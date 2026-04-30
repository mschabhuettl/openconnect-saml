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
    auth_settings.add_argument(
        "--auth-only",
        dest="auth_only",
        action="store_true",
        default=False,
        help="Friendly alias for --authenticate shell (auth, print cookie, exit)",
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
        "--on-error",
        dest="on_error",
        default="",
        help="Command to run if authentication or connect fails (receives exit code in $RC)",
    )
    parser.add_argument(
        "--detach",
        "--background",
        dest="detach",
        action="store_true",
        default=False,
        help="Daemonize after authentication; openconnect runs in the background. "
        "Stop with 'openconnect-saml disconnect [PROFILE]'",
    )
    parser.add_argument(
        "--wait",
        dest="wait_seconds",
        type=int,
        default=0,
        metavar="SECONDS",
        help=(
            "With --detach: block up to SECONDS until the tunnel interface "
            "is up before returning. Default 0 (return immediately)."
        ),
    )
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
    connection_group.add_argument(
        "--no-cert-check",
        dest="no_cert_check",
        action="store_true",
        default=False,
        help=(
            "Skip TLS certificate verification during the SAML auth phase. "
            "Use only with self-signed corporate gateways you trust. "
            "Also passed through to openconnect itself."
        ),
    )
    connection_group.add_argument(
        "--allowed-hosts",
        dest="allowed_hosts",
        default=None,
        metavar="HOST,HOST,...",
        help=(
            "Comma-separated whitelist of hostnames the headless redirect "
            "chain is allowed to traverse (supports '*.example.com'). "
            "The gateway and login URL hosts are auto-allowed."
        ),
    )
    cert_group = parser.add_argument_group("Client certificate (optional)")
    cert_group.add_argument(
        "--cert",
        dest="cert",
        default=None,
        metavar="FILE",
        help="Path to a client certificate (PEM) — passed to openconnect as --certificate",
    )
    cert_group.add_argument(
        "--cert-key",
        dest="cert_key",
        default=None,
        metavar="FILE",
        help="Path to the client cert's private key (PEM) — passed as --sslkey",
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
    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        default=False,
        help="Suppress informational output; only errors are printed",
    )


def create_argparser():
    """Create the main argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="openconnect-saml", description=openconnect_saml.__description__
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        default=False,
        help="Show version and exit (combine with --check to look up the latest on PyPI)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="With --version: also fetch the latest release from PyPI",
    )
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
    add_parser.add_argument(
        "--browser",
        default=None,
        choices=["qt", "chrome", "headless"],
        help="Default browser backend for this profile",
    )
    add_parser.add_argument(
        "--notify",
        dest="notify",
        action="store_true",
        default=None,
        help="Enable notifications by default for this profile",
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
        choices=["json", "nmconnection", "encrypted"],
        default="json",
        help=(
            "Export format (default: json). 'nmconnection' produces a NetworkManager "
            "VPN profile compatible with the Ubuntu/GNOME VPN UI. 'encrypted' produces "
            "a passphrase-protected backup (Fernet, PBKDF2-SHA256)."
        ),
    )

    import_parser = profiles_sub.add_parser("import", help="Import profiles from JSON")
    import_parser.add_argument("file", help="Input file (or '-' for stdin)")
    import_parser.add_argument(
        "--as", dest="as_name", default=None, help="Import under a different name"
    )
    import_parser.add_argument(
        "--force", action="store_true", default=False, help="Overwrite existing profiles"
    )

    copy_parser = profiles_sub.add_parser("copy", help="Duplicate a profile under a new name")
    copy_parser.add_argument("source", help="Source profile name")
    copy_parser.add_argument("dest", help="Target profile name")
    copy_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite the target profile if it already exists",
    )

    set_parser = profiles_sub.add_parser(
        "set", help="Programmatically set a single field on a profile"
    )
    set_parser.add_argument("profile_name")
    set_parser.add_argument(
        "field",
        help=(
            "Field to set: server, user_group, name, browser, notify, "
            "on_connect, on_disconnect, cert, cert_key, username, totp_source"
        ),
    )
    set_parser.add_argument(
        "value",
        help='Value (use "" to clear an optional field)',
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

    xml_parser = profiles_sub.add_parser(
        "import-xml", help="Import HostEntry blocks from an AnyConnect .xml profile"
    )
    xml_parser.add_argument("file", help="Path to a Cisco AnyConnect .xml profile")
    xml_parser.add_argument(
        "--prefix", default="", help="Prefix every imported profile name (default: none)"
    )
    xml_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing profiles with the same name",
    )

    # groups
    groups_parser = subparsers.add_parser(
        "groups", help="Manage and connect groups of profiles together"
    )
    groups_sub = groups_parser.add_subparsers(dest="groups_action")
    groups_sub.add_parser("list", help="List configured profile groups")
    groups_add = groups_sub.add_parser("add", help="Create or update a group")
    groups_add.add_argument("group_name")
    groups_add.add_argument("members", nargs="+", help="Profile names (in connect order)")
    groups_remove = groups_sub.add_parser("remove", help="Delete a group")
    groups_remove.add_argument("group_name")
    groups_connect = groups_sub.add_parser(
        "connect", help="Connect every profile in a group (uses --detach)"
    )
    groups_connect.add_argument("group_name")
    groups_disconnect = groups_sub.add_parser(
        "disconnect", help="Disconnect every profile in a group"
    )
    groups_disconnect.add_argument("group_name")
    groups_rename = groups_sub.add_parser("rename", help="Rename a group")
    groups_rename.add_argument("old_name")
    groups_rename.add_argument("new_name")

    # disconnect
    disconnect_parser = subparsers.add_parser(
        "disconnect", help="Stop a running VPN session by profile name"
    )
    disconnect_parser.add_argument(
        "profile_name",
        nargs="?",
        default=None,
        help="Profile to disconnect (default: all active sessions)",
    )
    disconnect_parser.add_argument(
        "--all", action="store_true", default=False, help="Disconnect every active session"
    )

    # sessions
    sessions_parser = subparsers.add_parser("sessions", help="List or inspect active VPN sessions")
    sessions_sub = sessions_parser.add_subparsers(dest="sessions_action")
    sessions_list = sessions_sub.add_parser("list", help="List active sessions")
    sessions_list.add_argument("--json", action="store_true", default=False)

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
        "shell_type",
        choices=[
            "bash",
            "zsh",
            "fish",
            "install",
            "_profiles",
            "_groups",
            "_sessions",
        ],
    )

    # setup
    setup_parser = subparsers.add_parser("setup", help="Interactive configuration wizard")
    setup_parser.add_argument(
        "--advanced",
        action="store_true",
        default=False,
        help="Also prompt for cert auth, on-connect/on-disconnect hooks, kill-switch",
    )

    # service
    subparsers.add_parser("service", help="Manage systemd VPN service", add_help=False)

    # gui
    subparsers.add_parser("gui", help="Open a Tk GUI for saved profiles")

    # tui
    subparsers.add_parser("tui", help="Interactive terminal UI (rich-based)")

    # run — connect, run a command, disconnect on exit
    run_parser = subparsers.add_parser(
        "run",
        help="Connect to a profile, run a command, then disconnect (transient session)",
    )
    run_parser.add_argument(
        "--wait",
        dest="run_wait",
        type=int,
        default=15,
        metavar="SECONDS",
        help="Seconds to wait for the tunnel before running the command (default: 15)",
    )
    run_parser.add_argument("profile_name", help="Profile to bring up")
    run_parser.add_argument(
        "command_argv",
        nargs=argparse.REMAINDER,
        help="The command to run (use -- to separate from arguments)",
    )

    # config
    config_parser = subparsers.add_parser("config", help="Inspect config file")
    config_sub = config_parser.add_subparsers(dest="config_action")
    config_sub.add_parser("path", help="Print path to config file")
    config_show = config_sub.add_parser("show", help="Show config (secrets redacted)")
    config_show.add_argument("--json", action="store_true", default=False)
    config_sub.add_parser("validate", help="Validate config file")
    config_sub.add_parser("edit", help="Open config file in $EDITOR")
    diff_parser = config_sub.add_parser(
        "diff", help="Show a unified diff against another config file"
    )
    diff_parser.add_argument("other_file", help="Path to the other TOML config")
    import_parser = config_sub.add_parser(
        "import", help="Merge another TOML config into the active one"
    )
    import_parser.add_argument("other_file", help="Path to the TOML config to import")
    import_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Let incoming values overwrite existing keys (default: keep existing)",
    )

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
    history_show.add_argument(
        "--filter",
        dest="filter_profile",
        default=None,
        metavar="PROFILE",
        help="Show only entries for this profile",
    )
    history_show.add_argument(
        "--event",
        dest="filter_event",
        default=None,
        choices=["connected", "disconnected", "reconnecting", "error"],
        help="Show only entries with this event type",
    )
    history_show.add_argument(
        "--since",
        dest="since",
        default=None,
        metavar="WHEN",
        help="ISO timestamp or relative phrase ('2 hours ago', '1 day ago')",
    )
    history_sub.add_parser("clear", help="Clear the history log")
    history_sub.add_parser("path", help="Print path to history file")
    history_stats = history_sub.add_parser("stats", help="Show aggregated connection statistics")
    history_stats.add_argument("--json", action="store_true", default=False)
    history_export = history_sub.add_parser(
        "export", help="Export the connection log as CSV or JSON"
    )
    history_export.add_argument("--file", "-o", default=None, help="Output file (default: stdout)")
    history_export.add_argument(
        "--format",
        "-f",
        default="csv",
        choices=["csv", "json"],
        help="Export format (default: csv)",
    )
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
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        default=False,
        help="Show version and exit",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="With --version: also fetch the latest release from PyPI",
    )
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

    def _add_user_flag(p):
        p.add_argument(
            "--user",
            "--user-unit",
            dest="user_mode",
            action="store_true",
            default=False,
            help="Use systemd --user (per-user unit, no sudo required)",
        )

    install_p = subparsers.add_parser("install", help="Install systemd unit")
    install_p.add_argument("-s", "--server", required=True)
    install_p.add_argument("-u", dest="user", default=None, help="VPN username")
    install_p.add_argument("--browser", choices=["headless", "chrome", "qt"], default="headless")
    install_p.add_argument("--max-retries", type=int, default=None)
    _add_user_flag(install_p)

    uninstall_p = subparsers.add_parser("uninstall", help="Remove systemd unit")
    uninstall_p.add_argument("-s", "--server", required=True)
    _add_user_flag(uninstall_p)

    start_p = subparsers.add_parser("start", help="Start VPN service")
    start_p.add_argument("-s", "--server", required=True)
    _add_user_flag(start_p)

    stop_p = subparsers.add_parser("stop", help="Stop VPN service")
    stop_p.add_argument("-s", "--server", required=True)
    _add_user_flag(stop_p)

    status_p = subparsers.add_parser("status", help="Show service status")
    status_p.add_argument("-s", "--server", default=None)
    _add_user_flag(status_p)

    logs_p = subparsers.add_parser("logs", help="Show service logs")
    logs_p.add_argument("-s", "--server", default=None)
    logs_p.add_argument("-f", "--follow", action="store_true")
    _add_user_flag(logs_p)

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
        if token == "--detach":
            args.detach = True
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


def _handle_setup_command(args=None):
    from openconnect_saml.setup_wizard import run_setup_wizard

    advanced = bool(getattr(args, "advanced", False)) if args is not None else False
    return run_setup_wizard(advanced=advanced)


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


def _handle_groups_command(args):
    from openconnect_saml import config as _config
    from openconnect_saml.sessions import kill, list_active

    action = getattr(args, "groups_action", None) or "list"
    cfg = _config.load()
    groups = getattr(cfg, "profile_groups", None) or {}

    if action == "list":
        if not groups:
            print("No profile groups configured.")
            print("Add one with: openconnect-saml groups add <name> <profile1> <profile2> ...")
            return 0
        print(f"{'Group':<20} Members")
        print("-" * 60)
        for gname, members in sorted(groups.items()):
            print(f"{gname:<20} {', '.join(members)}")
        return 0

    if action == "add":
        gname = args.group_name
        members = list(args.members)
        # Validate every member exists
        missing = [m for m in members if m not in cfg.profiles]
        if missing:
            print(f"Error: unknown profile(s): {', '.join(missing)}", file=sys.stderr)
            return 1
        groups[gname] = members
        cfg.profile_groups = groups
        _config.save(cfg)
        print(f"Saved group '{gname}' → {', '.join(members)}")
        return 0

    if action == "remove":
        gname = args.group_name
        if gname not in groups:
            print(f"Error: group '{gname}' not found.", file=sys.stderr)
            return 1
        del groups[gname]
        cfg.profile_groups = groups
        _config.save(cfg)
        print(f"Removed group '{gname}'.")
        return 0

    if action == "connect":
        gname = args.group_name
        if gname not in groups:
            print(f"Error: group '{gname}' not found.", file=sys.stderr)
            return 1
        members = list(groups[gname])
        if not members:
            print(f"Group '{gname}' has no members.", file=sys.stderr)
            return 1
        import subprocess as _sp  # nosec

        rc = 0
        for profile in members:
            cmd = [
                sys.executable,
                "-m",
                "openconnect_saml.cli",
                "connect",
                profile,
                "--detach",
            ]
            print(f"→ Connecting '{profile}'...")
            res = _sp.run(cmd, check=False)  # nosec
            if res.returncode != 0:
                print(f"  ! '{profile}' failed (exit {res.returncode})")
                rc = res.returncode
        return rc

    if action == "disconnect":
        gname = args.group_name
        if gname not in groups:
            print(f"Error: group '{gname}' not found.", file=sys.stderr)
            return 1
        active_names = {s.profile for s in list_active()}
        ok = 0
        for profile in groups[gname]:
            if profile in active_names and kill(profile):
                print(f"Disconnected '{profile}'.")
                ok += 1
        if not ok:
            print(f"No active sessions in group '{gname}'.")
            return 1
        return 0

    if action == "rename":
        old, new = args.old_name, args.new_name
        if old not in groups:
            print(f"Error: group '{old}' not found.", file=sys.stderr)
            return 1
        if new in groups:
            print(f"Error: group '{new}' already exists.", file=sys.stderr)
            return 1
        groups[new] = groups.pop(old)
        cfg.profile_groups = groups
        _config.save(cfg)
        print(f"Renamed group '{old}' → '{new}'.")
        return 0

    print(f"Unknown groups action: {action}")
    return 1


def _handle_disconnect_command(args):
    from openconnect_saml.sessions import kill, list_active

    profile = getattr(args, "profile_name", None)
    do_all = getattr(args, "all", False)

    if do_all or not profile:
        sessions = list_active()
        if not sessions:
            print("No active sessions.")
            return 0
        ok = 0
        for sess in sessions:
            if kill(sess.profile):
                print(f"Disconnected '{sess.profile}' (pid {sess.pid})")
                ok += 1
        return 0 if ok else 1

    if kill(profile):
        print(f"Disconnected '{profile}'.")
        return 0
    import difflib

    available = [s.profile for s in list_active()]
    close = difflib.get_close_matches(profile, available, n=3, cutoff=0.6)
    print(f"No active session for profile '{profile}'.")
    if close:
        print(f"Did you mean: {', '.join(close)}?")
    return 1


def _handle_sessions_command(args):
    import json as _json

    from openconnect_saml.sessions import list_active

    action = getattr(args, "sessions_action", None) or "list"
    sessions = list_active()
    if action == "list":
        as_json = getattr(args, "json", False)
        if as_json:
            print(_json.dumps([s.__dict__ for s in sessions], indent=2))
            return 0
        if not sessions:
            print("No active sessions.")
            return 0
        print(f"{'Profile':<14}  {'PID':>7}  {'Server':<28}  Started")
        print("-" * 80)
        for s in sessions:
            print(f"{s.profile:<14}  {s.pid:>7}  {s.server:<28}  {s.started_at}")
        return 0
    print(f"Unknown sessions action: {action}")
    return 1


def _handle_tui_command():
    from openconnect_saml.interactive_tui import handle_tui_command

    return handle_tui_command()


def _handle_run_command(args):
    """Connect to a profile in the background, run a command, then disconnect.

    The profile is brought up via ``connect --detach --wait``, the user's
    command runs in the foreground, and on exit (or signal) the profile
    is disconnected.
    """
    import signal as _signal
    import subprocess as _sp  # nosec

    from openconnect_saml.sessions import kill

    if not getattr(args, "command_argv", None):
        print("Error: no command given. Try: openconnect-saml run work -- curl …", file=sys.stderr)
        return 1

    cmd = list(args.command_argv)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Error: no command given after '--'.", file=sys.stderr)
        return 1

    # 1. Bring the profile up in detached mode and wait for the tunnel.
    bring_up = [
        sys.executable,
        "-m",
        "openconnect_saml.cli",
        "connect",
        args.profile_name,
        "--detach",
        "--wait",
        str(getattr(args, "run_wait", 15)),
    ]
    res = _sp.run(bring_up, check=False)  # nosec
    if res.returncode != 0:
        print(
            f"Error: could not bring up profile '{args.profile_name}' (exit {res.returncode}).",
            file=sys.stderr,
        )
        return res.returncode

    # 2. Run the user's command, forwarding stdin/stdout/stderr.
    rc = 1
    try:
        # Don't propagate Ctrl-C to ourselves until the child handled it.
        _signal.signal(_signal.SIGINT, _signal.SIG_IGN)
        rc = _sp.run(cmd, check=False).returncode  # nosec
    finally:
        _signal.signal(_signal.SIGINT, _signal.SIG_DFL)
        # 3. Tear the tunnel down regardless of how the command exited.
        try:
            kill(args.profile_name)
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: could not disconnect '{args.profile_name}': {exc}", file=sys.stderr)
    return rc


def _handle_connect(args, parser):
    """Handle the 'connect' subcommand or legacy invocation."""
    _recover_connect_options_from_remainder(args)
    if args.browser and args.browser == "headless":
        args.headless = True
    if getattr(args, "auth_only", False) and not args.authenticate:
        args.authenticate = "shell"

    if (getattr(args, "profile_path", None) or getattr(args, "use_profile_selector", False)) and (
        args.server or args.usergroup
    ):
        parser.error("--profile/--profile-selector and --server/--usergroup are mutually exclusive")

    profile_name = getattr(args, "profile_name", None)
    if profile_name:
        cfg = config.load()
        prof = cfg.get_profile(profile_name)
        if not prof:
            import difflib

            available = [name for name, _ in cfg.list_profiles()]
            close = difflib.get_close_matches(profile_name, available, n=3, cutoff=0.6)
            print(f"Error: profile '{profile_name}' not found.", file=sys.stderr)
            if close:
                print(
                    f"Did you mean: {', '.join(close)}?",
                    file=sys.stderr,
                )
            print("Available profiles:", file=sys.stderr)
            for name in available:
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
        "disconnect",
        "sessions",
        "groups",
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
        "run",
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


def _apply_quiet_flag(args):
    """``--quiet`` raises the log threshold to WARNING for the duration."""
    if getattr(args, "quiet", False) and (
        getattr(args, "log_level", LogLevel.INFO) is None or args.log_level <= LogLevel.INFO
    ):
        args.log_level = LogLevel.WARNING


def _maybe_first_run_hint(argv) -> None:
    """Print a one-shot suggestion to run ``setup`` when the user has no
    config yet and ran a command that needs one. Only fires on TTYs and
    only when no command-line server was given.
    """
    if not sys.stdout.isatty():
        return
    if not argv:
        return
    # Skip for setup itself, completion helpers, doctor, version
    skip = {"setup", "completion", "doctor", "config", "--version", "-V"}
    if argv[0] in skip:
        return
    # If the user already provided --server/-s, no first-run hint needed
    if any(a in ("-s", "--server") for a in argv):
        return
    cfg = config.load()
    if cfg.profiles or cfg.default_profile:
        return
    print(
        "👋 Looks like this is your first run — no profiles configured yet.",
        file=sys.stderr,
    )
    print(
        "   Run `openconnect-saml setup` to create one interactively, "
        "or pass --server vpn.example.com directly.",
        file=sys.stderr,
    )


def _print_version(check: bool = False) -> int:
    print(f"openconnect-saml {__version__}")
    if check:
        from openconnect_saml.version_check import check as _check

        info = _check()
        if info.latest is None:
            print("(could not contact PyPI to check for updates)")
            return 0
        if info.is_outdated:
            print(info.hint_line() or "")
        else:
            print("You are running the latest version.")
    return 0


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
        if getattr(args, "version", False):
            return _print_version(check=getattr(args, "check", False))
        _apply_config_override(args)
        _apply_quiet_flag(args)
        _maybe_first_run_hint(argv)

        if args.command == "connect":
            return _handle_connect(args, parser)
        if args.command == "profiles":
            return _handle_profiles_command(args)
        if args.command == "status":
            return _handle_status_command(args)
        if args.command == "completion":
            return _handle_completion_command(args)
        if args.command == "setup":
            return _handle_setup_command(args)
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
        if args.command == "run":
            return _handle_run_command(args)
        if args.command == "disconnect":
            return _handle_disconnect_command(args)
        if args.command == "sessions":
            return _handle_sessions_command(args)
        if args.command == "groups":
            return _handle_groups_command(args)

        parser.print_help()
        return 0

    # Legacy mode: no subcommand
    parser = create_legacy_argparser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        return _print_version(check=getattr(args, "check", False))
    _apply_config_override(args)
    _apply_quiet_flag(args)
    args.profile_name = None
    return _handle_connect(args, parser)


if __name__ == "__main__":
    sys.exit(main())
