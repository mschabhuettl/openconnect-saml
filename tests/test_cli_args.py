"""Tests for CLI argument parsing — all flags including new ones."""

import pytest

from openconnect_saml.cli import create_argparser as _create_argparser
from openconnect_saml.cli import create_legacy_argparser as create_argparser


@pytest.fixture
def parser():
    return create_argparser()


@pytest.fixture
def main_parser():
    return _create_argparser()


class TestTotpFlags:
    def test_totp_source_none_accepted(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--totp-source", "none"])
        assert args.totp_source == "none"

    def test_no_totp_flag(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--no-totp"])
        assert args.no_totp is True

    def test_no_totp_default(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.no_totp is False

    def test_profiles_add_totp_none(self, main_parser):
        args = main_parser.parse_args(
            ["profiles", "add", "work", "--server", "vpn.example.com", "--totp-source", "none"]
        )
        assert args.totp_source == "none"


class TestConfigOverride:
    def test_global_config_flag(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--config", "/tmp/x.toml"])
        assert args.config_file == "/tmp/x.toml"

    def test_main_parser_config_flag(self, main_parser):
        args = main_parser.parse_args(["--config", "/tmp/x.toml", "status"])
        assert args.config_file == "/tmp/x.toml"


class TestStatusJson:
    def test_status_json_flag(self, main_parser):
        args = main_parser.parse_args(["status", "--json"])
        assert args.json is True

    def test_status_json_default(self, main_parser):
        args = main_parser.parse_args(["status"])
        assert args.json is False


class TestHistoryStats:
    def test_history_stats_subcommand(self, main_parser):
        args = main_parser.parse_args(["history", "stats"])
        assert args.history_action == "stats"

    def test_history_stats_json(self, main_parser):
        args = main_parser.parse_args(["history", "stats", "--json"])
        assert args.json is True


class TestDoctorJson:
    def test_doctor_json_flag(self, main_parser):
        args = main_parser.parse_args(["doctor", "--json"])
        assert args.json is True


class TestProfilesMigrate:
    def test_migrate_subcommand(self, main_parser):
        args = main_parser.parse_args(["profiles", "migrate"])
        assert args.profiles_action == "migrate"
        assert args.apply is False

    def test_migrate_apply(self, main_parser):
        args = main_parser.parse_args(["profiles", "migrate", "--apply"])
        assert args.apply is True


class TestTuiSubcommand:
    def test_tui_subcommand_recognized(self, main_parser):
        args = main_parser.parse_args(["tui"])
        assert args.command == "tui"


class TestDetachFlag:
    def test_detach_default_false(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.detach is False

    def test_detach_flag(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--detach"])
        assert args.detach is True

    def test_detach_on_connect_subcommand(self, main_parser):
        # --detach before the profile name is consumed by argparse directly.
        args = main_parser.parse_args(
            ["connect", "--detach", "work", "--server", "vpn.example.com"]
        )
        assert args.detach is True

    def test_detach_after_profile_recovered_by_main(self):
        # --detach swallowed into argparse.REMAINDER after `connect PROFILE`
        # is recovered by _recover_connect_options_from_remainder.
        from types import SimpleNamespace

        from openconnect_saml.cli import _recover_connect_options_from_remainder

        args = SimpleNamespace(
            openconnect_args=["--server", "vpn.example.com", "--detach"],
            detach=False,
            browser=None,
            headless=False,
        )
        _recover_connect_options_from_remainder(args)
        assert args.detach is True
        assert "--detach" not in args.openconnect_args


class TestDisconnectSubcommand:
    def test_disconnect_no_profile(self, main_parser):
        args = main_parser.parse_args(["disconnect"])
        assert args.command == "disconnect"
        assert args.profile_name is None

    def test_disconnect_with_profile(self, main_parser):
        args = main_parser.parse_args(["disconnect", "work"])
        assert args.profile_name == "work"

    def test_disconnect_all(self, main_parser):
        args = main_parser.parse_args(["disconnect", "--all"])
        assert args.all is True


class TestSessionsSubcommand:
    def test_sessions_default_action(self, main_parser):
        args = main_parser.parse_args(["sessions"])
        assert args.command == "sessions"

    def test_sessions_list(self, main_parser):
        args = main_parser.parse_args(["sessions", "list"])
        assert args.sessions_action == "list"

    def test_sessions_list_json(self, main_parser):
        args = main_parser.parse_args(["sessions", "list", "--json"])
        assert args.json is True


class TestExportFormatFlag:
    def test_export_format_default_json(self, main_parser):
        args = main_parser.parse_args(["profiles", "export", "work"])
        assert args.format == "json"

    def test_export_format_nmconnection(self, main_parser):
        args = main_parser.parse_args(["profiles", "export", "work", "--format", "nmconnection"])
        assert args.format == "nmconnection"

    def test_export_format_short_flag(self, main_parser):
        args = main_parser.parse_args(["profiles", "export", "work", "-f", "nmconnection"])
        assert args.format == "nmconnection"

    def test_export_format_invalid(self, main_parser):
        with pytest.raises(SystemExit):
            main_parser.parse_args(["profiles", "export", "work", "--format", "yaml"])


class TestBasicArgs:
    def test_server_arg(self, parser):
        args = parser.parse_args(["--server", "vpn.example.com"])
        assert args.server == "vpn.example.com"

    def test_server_short(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.server == "vpn.example.com"

    def test_user_arg(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--user", "testuser"])
        assert args.user == "testuser"

    def test_user_short(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "-u", "testuser"])
        assert args.user == "testuser"

    def test_proxy_arg(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--proxy", "http://proxy:8080"])
        assert args.proxy == "http://proxy:8080"


class TestNewFlags:
    def test_no_sudo(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--no-sudo"])
        assert args.no_sudo is True

    def test_no_sudo_default(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.no_sudo is False

    def test_csd_wrapper(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--csd-wrapper", "/path/to/csd.sh"])
        assert args.csd_wrapper == "/path/to/csd.sh"

    def test_csd_wrapper_default(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.csd_wrapper is None

    def test_ssl_legacy(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--ssl-legacy"])
        assert args.ssl_legacy is True

    def test_ssl_legacy_default(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.ssl_legacy is False

    def test_timeout(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--timeout", "60"])
        assert args.timeout == 60

    def test_timeout_default(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.timeout is None

    def test_window_size(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--window-size", "1024x768"])
        assert args.window_size == "1024x768"

    def test_window_size_default(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.window_size is None

    def test_on_connect(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--on-connect", "/usr/bin/script.sh"])
        assert args.on_connect == "/usr/bin/script.sh"

    def test_on_disconnect(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--on-disconnect", "/usr/bin/down.sh"])
        assert args.on_disconnect == "/usr/bin/down.sh"

    def test_reset_credentials(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--reset-credentials"])
        assert args.reset_credentials is True


class TestAuthenticateFlag:
    def test_authenticate_json(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--authenticate", "json"])
        assert args.authenticate == "json"

    def test_authenticate_shell(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--authenticate", "shell"])
        assert args.authenticate == "shell"

    def test_authenticate_default_is_shell(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--authenticate"])
        assert args.authenticate == "shell"

    def test_no_authenticate(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.authenticate is False


class TestBrowserDisplayMode:
    def test_shown(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--browser-display-mode", "shown"])
        assert args.browser_display_mode == "shown"

    def test_hidden(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--browser-display-mode", "hidden"])
        assert args.browser_display_mode == "hidden"

    def test_default_shown(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.browser_display_mode == "shown"


class TestLogLevel:
    def test_debug(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "-l", "DEBUG"])
        assert args.log_level == 10

    def test_error(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "-l", "ERROR"])
        assert args.log_level == 40

    def test_default_info(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.log_level == 20


class TestOpenConnectArgs:
    def test_passthrough_args(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com", "--", "--protocol", "anyconnect"])
        assert args.openconnect_args == ["--protocol", "anyconnect"]

    def test_no_passthrough(self, parser):
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.openconnect_args == []
