"""Tests for the Bitwarden TOTP provider."""

from unittest.mock import MagicMock, patch

from openconnect_saml.totp_providers import BitwardenProvider


class TestBitwardenProvider:
    def test_init(self):
        provider = BitwardenProvider(item_id="abc-123")
        assert provider.item_id == "abc-123"
        assert provider.timeout == 10

    def test_custom_timeout(self):
        provider = BitwardenProvider(item_id="abc-123", timeout=30)
        assert provider.timeout == 30

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch("openconnect_saml.totp_providers.subprocess.run")
    def test_get_totp_success(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="123456\n",
            stderr="",
        )
        provider = BitwardenProvider(item_id="test-uuid")
        result = provider.get_totp()
        assert result == "123456"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args == ["/usr/bin/bw", "get", "totp", "test-uuid"]

    @patch("openconnect_saml.totp_providers.shutil.which", return_value=None)
    def test_bw_not_found(self, mock_which):
        provider = BitwardenProvider(item_id="test-uuid")
        result = provider.get_totp()
        assert result is None

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch("openconnect_saml.totp_providers.subprocess.run")
    def test_vault_locked(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Vault is locked.",
        )
        provider = BitwardenProvider(item_id="test-uuid")
        result = provider.get_totp()
        assert result is None

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch("openconnect_saml.totp_providers.subprocess.run")
    def test_not_logged_in(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="You are not logged in.",
        )
        provider = BitwardenProvider(item_id="test-uuid")
        result = provider.get_totp()
        assert result is None

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch("openconnect_saml.totp_providers.subprocess.run")
    def test_item_not_found(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Not found.",
        )
        provider = BitwardenProvider(item_id="nonexistent")
        result = provider.get_totp()
        assert result is None

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch("openconnect_saml.totp_providers.subprocess.run")
    def test_empty_output(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="",
            stderr="",
        )
        provider = BitwardenProvider(item_id="test-uuid")
        result = provider.get_totp()
        assert result is None

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch(
        "openconnect_saml.totp_providers.subprocess.run",
        side_effect=TimeoutError,
    )
    def test_timeout(self, mock_run, mock_which):
        """Timeout raises subprocess.TimeoutExpired in real code."""
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("bw", 10)
        provider = BitwardenProvider(item_id="test-uuid", timeout=1)
        result = provider.get_totp()
        assert result is None

    @patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/bw")
    @patch("openconnect_saml.totp_providers.subprocess.run")
    def test_generic_error(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Something unexpected happened",
        )
        provider = BitwardenProvider(item_id="test-uuid")
        result = provider.get_totp()
        assert result is None


class TestBitwardenConfig:
    def test_config_from_dict(self):
        from openconnect_saml.config import BitwardenConfig

        cfg = BitwardenConfig.from_dict({"item_id": "abc-123"})
        assert cfg.item_id == "abc-123"

    def test_config_as_dict(self):
        from openconnect_saml.config import BitwardenConfig

        cfg = BitwardenConfig(item_id="abc-123")
        d = cfg.as_dict()
        assert d["item_id"] == "abc-123"

    def test_config_none(self):
        from openconnect_saml.config import BitwardenConfig

        assert BitwardenConfig.from_dict(None) is None
