"""Tests for the interactive setup wizard."""

from unittest.mock import MagicMock, patch

import pytest

from openconnect_saml.setup_wizard import (
    _maybe_offer_xml_import,
    _prompt,
    _prompt_choice,
    _prompt_yes_no,
    _scan_anyconnect_xml_dirs,
    run_setup_wizard,
)


class TestPrompt:
    @patch("builtins.input", return_value="test-value")
    def test_basic_input(self, mock_input):
        result = _prompt("Enter value")
        assert result == "test-value"

    @patch("builtins.input", return_value="")
    def test_default_value(self, mock_input):
        result = _prompt("Enter value", default="fallback")
        assert result == "fallback"

    @patch("builtins.input", side_effect=["", "value"])
    def test_required_retries(self, mock_input):
        result = _prompt("Enter value", required=True)
        assert result == "value"


class TestPromptChoice:
    @patch("builtins.input", return_value="local")
    def test_valid_choice(self, mock_input):
        result = _prompt_choice("Choose", ["local", "2fauth", "bitwarden"])
        assert result == "local"

    @patch("builtins.input", return_value="")
    def test_default_choice(self, mock_input):
        result = _prompt_choice("Choose", ["local", "2fauth"], default="local")
        assert result == "local"

    @patch("builtins.input", side_effect=["invalid", "local"])
    def test_invalid_retries(self, mock_input):
        result = _prompt_choice("Choose", ["local", "2fauth"])
        assert result == "local"


class TestPromptYesNo:
    @patch("builtins.input", return_value="y")
    def test_yes(self, mock_input):
        assert _prompt_yes_no("Continue?") is True

    @patch("builtins.input", return_value="n")
    def test_no(self, mock_input):
        assert _prompt_yes_no("Continue?") is False

    @patch("builtins.input", return_value="")
    def test_default_true(self, mock_input):
        assert _prompt_yes_no("Continue?", default=True) is True

    @patch("builtins.input", return_value="")
    def test_default_false(self, mock_input):
        assert _prompt_yes_no("Continue?", default=False) is False

    @patch("builtins.input", return_value="ja")
    def test_german_yes(self, mock_input):
        assert _prompt_yes_no("Weiter?") is True


class TestRunSetupWizard:
    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",  # server
            "user@example.com",  # username
            "local",  # totp source
            "headless",  # browser mode
            "y",  # auto-reconnect
            "n",  # notifications
            "work",  # profile name
            "y",  # save?
            "y",  # set as default?
        ],
    )
    def test_basic_wizard(self, mock_input, mock_config):
        mock_cfg = MagicMock()
        mock_cfg.default_profile = None
        mock_cfg.profiles = {}
        mock_config.load.return_value = mock_cfg

        result = run_setup_wizard()
        assert result == 0
        mock_config.save.assert_called_once()

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",  # server
            "user@example.com",  # username
            "bitwarden",  # totp source
            "abc-uuid-123",  # bitwarden item id
            "headless",  # browser mode
            "y",  # auto-reconnect
            "n",  # notifications
            "myprofile",  # profile name
            "y",  # save?
            "y",  # set as default?
        ],
    )
    def test_wizard_bitwarden(self, mock_input, mock_config):
        mock_cfg = MagicMock()
        mock_cfg.default_profile = None
        mock_cfg.profiles = {}
        mock_config.load.return_value = mock_cfg

        result = run_setup_wizard()
        assert result == 0
        # Should set bitwarden config
        assert mock_cfg.bitwarden is not None

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",  # server
            "user@example.com",  # username
            "2fauth",  # totp source
            "https://2fa.example",  # 2fauth url
            "my-token",  # 2fauth token
            "42",  # 2fauth account id
            "chrome",  # browser mode
            "n",  # auto-reconnect
            "y",  # notifications
            "lab",  # profile name
            "y",  # save?
            "y",  # set as default?
        ],
    )
    def test_wizard_2fauth(self, mock_input, mock_config):
        mock_cfg = MagicMock()
        mock_cfg.default_profile = None
        mock_cfg.profiles = {}
        mock_config.load.return_value = mock_cfg

        result = run_setup_wizard()
        assert result == 0
        assert mock_cfg.twofauth is not None

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",  # server
            "user@example.com",  # username
            "local",  # totp source
            "headless",  # browser mode
            "y",  # auto-reconnect
            "n",  # notifications
            "work",  # profile name
            "n",  # save? -> abort
        ],
    )
    def test_wizard_abort(self, mock_input, mock_config):
        result = run_setup_wizard()
        assert result == 1
        mock_config.save.assert_not_called()


# --------------------------------------------------------------- prompt edge cases


class TestPromptInterruption:
    """Both EOF (^D) and KeyboardInterrupt (^C) abort the wizard."""

    @patch("builtins.input", side_effect=EOFError)
    def test_prompt_handles_eof(self, _mi):
        with pytest.raises(SystemExit) as exc_info:
            _prompt("Server")
        assert exc_info.value.code == 1

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_prompt_handles_ctrl_c(self, _mi):
        with pytest.raises(SystemExit) as exc_info:
            _prompt("Server")
        assert exc_info.value.code == 1

    @patch("builtins.input", side_effect=EOFError)
    def test_prompt_choice_handles_eof(self, _mi):
        with pytest.raises(SystemExit) as exc_info:
            _prompt_choice("Mode", ["a", "b"])
        assert exc_info.value.code == 1

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_prompt_yes_no_handles_ctrl_c(self, _mi):
        with pytest.raises(SystemExit) as exc_info:
            _prompt_yes_no("Continue?")
        assert exc_info.value.code == 1


# ---------------------------------------------------- _scan_anyconnect_xml_dirs


class TestScanAnyConnectXmlDirs:
    def test_returns_empty_when_no_dirs_exist(self, tmp_path):
        # Point Path.home() at an empty tmp dir; the system /opt dirs
        # are unlikely to exist on the test runner.
        empty_home = tmp_path / "home"
        empty_home.mkdir()
        with patch("pathlib.Path.home", return_value=empty_home):
            result = _scan_anyconnect_xml_dirs()
        # On a CI box without /opt/cisco, we should get [].
        assert all(not p.startswith(str(empty_home)) for p in result)

    def test_returns_xml_files_from_home_cisco_profile(self, tmp_path):
        cisco_dir = tmp_path / ".cisco" / "profile"
        cisco_dir.mkdir(parents=True)
        (cisco_dir / "test.xml").write_text("<dummy/>")
        (cisco_dir / "ignore.txt").write_text("nope")

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = _scan_anyconnect_xml_dirs()
        assert any(p.endswith("test.xml") for p in result)
        assert not any(p.endswith("ignore.txt") for p in result)


# ------------------------------------------------------- _maybe_offer_xml_import


class TestMaybeOfferXmlImport:
    def test_no_files_short_circuits(self):
        with patch("openconnect_saml.setup_wizard._scan_anyconnect_xml_dirs", return_value=[]):
            assert _maybe_offer_xml_import() is False

    def test_user_declines(self, capsys):
        with (
            patch(
                "openconnect_saml.setup_wizard._scan_anyconnect_xml_dirs",
                return_value=["/path/to/foo.xml"],
            ),
            patch("openconnect_saml.setup_wizard._prompt_yes_no", return_value=False),
        ):
            assert _maybe_offer_xml_import() is False
        out = capsys.readouterr().out
        assert "foo.xml" in out

    def test_imports_new_profile(self, tmp_path, capsys):
        from types import SimpleNamespace

        from openconnect_saml import config as _config

        # Build a host_profile-like object the way profile.py returns them.
        hp = SimpleNamespace(name="WorkVPN", address="vpn.work.example", user_group="g1")
        cfg = _config.Config()
        with (
            patch(
                "openconnect_saml.setup_wizard._scan_anyconnect_xml_dirs",
                return_value=[str(tmp_path / "p.xml")],
            ),
            patch("openconnect_saml.setup_wizard._prompt_yes_no", return_value=True),
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.config.save") as save,
            patch(
                "openconnect_saml.profile._get_profiles_from_one_file",
                return_value=[hp],
            ),
        ):
            assert _maybe_offer_xml_import() is True
        save.assert_called_once()
        # Profile name normalised: spaces → underscores.
        assert "WorkVPN" in cfg.profiles

    def test_skips_existing_profile(self, tmp_path, capsys):
        from types import SimpleNamespace

        from openconnect_saml import config as _config

        hp = SimpleNamespace(name="dup", address="vpn.dup", user_group="")
        cfg = _config.Config()
        cfg.add_profile("dup", {"server": "old"})
        with (
            patch(
                "openconnect_saml.setup_wizard._scan_anyconnect_xml_dirs",
                return_value=[str(tmp_path / "x.xml")],
            ),
            patch("openconnect_saml.setup_wizard._prompt_yes_no", return_value=True),
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.config.save") as save,
            patch(
                "openconnect_saml.profile._get_profiles_from_one_file",
                return_value=[hp],
            ),
        ):
            # No new profile imported → returns False, no save.
            assert _maybe_offer_xml_import() is False
        save.assert_not_called()

    def test_handles_parser_failure(self, tmp_path, capsys):
        from openconnect_saml import config as _config

        cfg = _config.Config()
        with (
            patch(
                "openconnect_saml.setup_wizard._scan_anyconnect_xml_dirs",
                return_value=[str(tmp_path / "broken.xml")],
            ),
            patch("openconnect_saml.setup_wizard._prompt_yes_no", return_value=True),
            patch("openconnect_saml.config.load", return_value=cfg),
            patch(
                "openconnect_saml.profile._get_profiles_from_one_file",
                side_effect=ValueError("malformed"),
            ),
        ):
            assert _maybe_offer_xml_import() is False
        assert "could not parse" in capsys.readouterr().out


# --------------------------------------------------------- additional wizard branches


class TestRunWizardExtras:
    def test_wizard_short_circuits_when_xml_imported(self, capsys):
        with patch("openconnect_saml.setup_wizard._maybe_offer_xml_import", return_value=True):
            assert run_setup_wizard() == 0
        assert "openconnect-saml connect" in capsys.readouterr().out

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",  # server
            "user@example.com",  # username
            "2fauth",  # totp source
            "https://2fa.example",  # url
            "tok",  # token
            "not-a-number",  # account id (invalid)
        ],
    )
    def test_2fauth_invalid_account_id_aborts(self, _mi, mock_config, capsys):
        # No XML import path available.
        with patch("openconnect_saml.setup_wizard._maybe_offer_xml_import", return_value=False):
            rc = run_setup_wizard()
        out = capsys.readouterr().out
        assert rc == 1
        assert "number" in out

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",  # server
            "alice",  # username
            "1password",  # totp source
            "Login - work",  # 1Password item name
            "Personal",  # vault
            "",  # account
            "headless",  # browser
            "y",  # auto-reconnect
            "n",  # notifications
            "work",  # profile name
            "y",  # save?
            "y",  # set as default?
        ],
    )
    def test_1password_branch(self, _mi, mock_config):
        mock_cfg = MagicMock()
        mock_cfg.default_profile = None
        mock_cfg.profiles = {}
        mock_config.load.return_value = mock_cfg
        with patch("openconnect_saml.setup_wizard._maybe_offer_xml_import", return_value=False):
            rc = run_setup_wizard()
        assert rc == 0
        assert mock_cfg.onepassword is not None

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",
            "alice",
            "pass",  # totp source
            "work/vpn-totp",  # entry path
            "headless",
            "y",
            "n",
            "work",
            "y",
            "y",
        ],
    )
    def test_pass_branch(self, _mi, mock_config):
        mock_cfg = MagicMock()
        mock_cfg.default_profile = None
        mock_cfg.profiles = {}
        mock_config.load.return_value = mock_cfg
        with patch("openconnect_saml.setup_wizard._maybe_offer_xml_import", return_value=False):
            rc = run_setup_wizard()
        assert rc == 0
        assert mock_cfg.pass_ is not None

    @patch("openconnect_saml.setup_wizard.config")
    @patch(
        "builtins.input",
        side_effect=[
            "vpn.example.com",
            "alice",
            "local",
            "headless",
            "y",  # auto-reconnect
            "n",  # notifications
            # advanced=True branch:
            "/etc/ssl/cert.pem",  # cert path
            "/etc/ssl/key.pem",  # key path (required because cert set)
            "/usr/bin/notify-up",  # on-connect
            "/usr/bin/notify-down",  # on-disconnect
            "y",  # killswitch
            "work",  # profile name
            "y",  # save?
            "y",  # default?
        ],
    )
    def test_wizard_advanced_branch(self, _mi, mock_config):
        mock_cfg = MagicMock()
        mock_cfg.default_profile = None
        mock_cfg.profiles = {}
        mock_config.load.return_value = mock_cfg
        with patch("openconnect_saml.setup_wizard._maybe_offer_xml_import", return_value=False):
            rc = run_setup_wizard(advanced=True)
        assert rc == 0
        # Final add_profile call should carry the advanced fields.
        called_with = mock_cfg.add_profile.call_args.args
        assert "cert" in called_with[1]
        assert "kill_switch" in called_with[1]
