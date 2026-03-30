"""Tests for config edge cases: corrupt, missing, empty, None values."""

from unittest.mock import patch

from openconnect_saml.config import (
    AutoFillRule,
    Config,
    Credentials,
    HostProfile,
    load,
)


class TestConfigLoading:
    """Config load edge cases."""

    @patch("openconnect_saml.config.xdg.BaseDirectory.load_first_config")
    def test_load_no_config_dir(self, mock_load):
        """No config directory should return default Config."""
        mock_load.return_value = None
        cfg = load()
        assert isinstance(cfg, Config)
        assert cfg.default_profile is None

    @patch("openconnect_saml.config.xdg.BaseDirectory.load_first_config")
    def test_load_missing_config_file(self, mock_load, tmp_path):
        """Config dir exists but file doesn't."""
        mock_load.return_value = str(tmp_path)
        cfg = load()
        assert isinstance(cfg, Config)

    @patch("openconnect_saml.config.xdg.BaseDirectory.load_first_config")
    def test_load_corrupt_config_file(self, mock_load, tmp_path):
        """Corrupt TOML should return default Config, not crash."""
        mock_load.return_value = str(tmp_path)
        config_file = tmp_path / "config.toml"
        config_file.write_text("this is not valid toml {{{{")
        cfg = load()
        assert isinstance(cfg, Config)

    @patch("openconnect_saml.config.xdg.BaseDirectory.load_first_config")
    def test_load_empty_config_file(self, mock_load, tmp_path):
        """Empty TOML file should return default Config."""
        mock_load.return_value = str(tmp_path)
        config_file = tmp_path / "config.toml"
        config_file.write_text("")
        cfg = load()
        assert isinstance(cfg, Config)


class TestConfigNoneValues:
    """Config with None values for int fields."""

    def test_timeout_none_uses_default(self):
        cfg = Config.from_dict({"timeout": None})
        assert cfg.timeout == 30

    def test_window_width_none_uses_default(self):
        cfg = Config.from_dict({"window_width": None})
        assert cfg.window_width == 800

    def test_window_height_none_uses_default(self):
        cfg = Config.from_dict({"window_height": None})
        assert cfg.window_height == 600

    def test_timeout_string_converts(self):
        cfg = Config.from_dict({"timeout": "60"})
        assert cfg.timeout == 60


class TestHostProfile:
    """HostProfile edge cases."""

    def test_empty_address(self):
        hp = HostProfile("", "", "")
        url = hp.vpn_url
        assert isinstance(url, str)

    def test_special_chars_in_group(self):
        hp = HostProfile("server.com", "group with spaces", "name")
        url = hp.vpn_url
        assert "server.com" in url

    def test_address_with_port(self):
        hp = HostProfile("https://server.com:8443", "", "name")
        assert "8443" in hp.vpn_url


class TestCredentials:
    """Credentials edge cases."""

    @patch("openconnect_saml.config.keyring")
    def test_password_keyring_error(self, mock_keyring):
        """KeyringError on password retrieval returns empty string."""
        mock_keyring.errors.KeyringError = Exception
        mock_keyring.get_password.side_effect = Exception("no keyring")
        cred = Credentials("testuser")
        assert cred.password == ""

    @patch("openconnect_saml.config.keyring")
    def test_totp_keyring_error(self, mock_keyring):
        """KeyringError on TOTP retrieval returns empty string."""
        mock_keyring.errors.KeyringError = Exception
        mock_keyring.get_password.side_effect = Exception("no keyring")
        cred = Credentials("testuser")
        assert cred.totp == ""

    @patch("openconnect_saml.config.keyring")
    def test_save_keyring_error(self, mock_keyring):
        """KeyringError on save should not crash."""
        mock_keyring.errors.KeyringError = Exception
        mock_keyring.set_password.side_effect = Exception("no keyring")
        cred = Credentials("testuser")
        cred._password = "test"
        cred._totp_secret = "JBSWY3DPEHPK3PXP"
        cred.save()  # Should not raise

    @patch("openconnect_saml.config.keyring")
    def test_delete_keyring_error(self, mock_keyring):
        """KeyringError on delete should not crash."""
        mock_keyring.errors.KeyringError = Exception
        mock_keyring.delete_password.side_effect = Exception("no keyring")
        cred = Credentials("testuser")
        del cred.password  # Should not raise
        del cred.totp  # Should not raise


class TestAutoFillRule:
    """AutoFillRule edge cases."""

    def test_from_dict_none(self):
        result = AutoFillRule.from_dict(None)
        assert result is None

    def test_from_dict_minimal(self):
        rule = AutoFillRule.from_dict({"selector": "input"})
        assert rule.selector == "input"
        assert rule.fill is None
        assert rule.action is None
