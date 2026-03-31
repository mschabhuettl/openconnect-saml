"""Tests for the interactive setup wizard."""

from unittest.mock import MagicMock, patch

from openconnect_saml.setup_wizard import (
    _prompt,
    _prompt_choice,
    _prompt_yes_no,
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
