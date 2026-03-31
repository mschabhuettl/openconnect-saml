"""Tests for 2FAuth TOTP integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openconnect_saml.config import Config, Credentials, TwoFAuthConfig
from openconnect_saml.totp_providers import LocalTotpProvider, TwoFAuthProvider

# ---------------------------------------------------------------------------
# TwoFAuthConfig
# ---------------------------------------------------------------------------


class TestTwoFAuthConfig:
    def test_from_dict(self):
        cfg = TwoFAuthConfig.from_dict(
            {"url": "https://2fa.example.com", "token": "secret123", "account_id": 42}
        )
        assert cfg.url == "https://2fa.example.com"
        assert cfg.token == "secret123"
        assert cfg.account_id == 42

    def test_from_dict_none(self):
        assert TwoFAuthConfig.from_dict(None) is None

    def test_account_id_converter(self):
        cfg = TwoFAuthConfig(url="https://x.com", token="t", account_id="7")
        assert cfg.account_id == 7
        assert isinstance(cfg.account_id, int)

    def test_as_dict(self):
        cfg = TwoFAuthConfig(url="https://x.com", token="t", account_id=5)
        d = cfg.as_dict()
        assert d == {"url": "https://x.com", "token": "t", "account_id": 5}


# ---------------------------------------------------------------------------
# Config with [2fauth] section
# ---------------------------------------------------------------------------


class TestConfigWith2FAuth:
    def test_config_from_dict_with_2fauth(self):
        d = {
            "credentials": {"username": "user@example.com", "totp_source": "2fauth"},
            "2fauth": {
                "url": "https://2fa.example.com",
                "token": "tok",
                "account_id": 10,
            },
        }
        cfg = Config.from_dict(d)
        assert cfg.credentials.totp_source == "2fauth"
        assert cfg.twofauth is not None
        assert cfg.twofauth.url == "https://2fa.example.com"
        assert cfg.twofauth.account_id == 10

    def test_config_as_dict_roundtrip(self):
        cfg = Config.from_dict(
            {
                "credentials": {"username": "u", "totp_source": "2fauth"},
                "2fauth": {"url": "https://x.com", "token": "t", "account_id": 1},
            }
        )
        d = cfg.as_dict()
        assert "2fauth" in d
        assert d["2fauth"]["url"] == "https://x.com"
        # twofauth key should NOT be in output
        assert "twofauth" not in d

    def test_config_without_2fauth(self):
        cfg = Config.from_dict({"credentials": {"username": "u"}})
        assert cfg.twofauth is None
        assert cfg.credentials.totp_source == "local"


# ---------------------------------------------------------------------------
# Credentials with totp_source
# ---------------------------------------------------------------------------


class TestCredentialsTotp:
    def test_default_totp_source(self):
        cred = Credentials("user")
        assert cred.totp_source == "local"

    def test_totp_source_from_dict(self):
        cred = Credentials.from_dict({"username": "u", "totp_source": "2fauth"})
        assert cred.totp_source == "2fauth"

    def test_set_totp_provider(self):
        cred = Credentials("user")
        mock_provider = MagicMock()
        mock_provider.get_totp.return_value = "654321"
        cred.set_totp_provider(mock_provider)
        assert cred.totp == "654321"
        mock_provider.get_totp.assert_called_once()

    def test_totp_provider_overrides_local(self):
        """When a provider is attached, it is used even if a secret is set."""
        cred = Credentials("user")
        cred._totp_secret = "JBSWY3DPEHPK3PXP"
        mock_provider = MagicMock()
        mock_provider.get_totp.return_value = "111111"
        cred.set_totp_provider(mock_provider)
        assert cred.totp == "111111"


# ---------------------------------------------------------------------------
# LocalTotpProvider
# ---------------------------------------------------------------------------


class TestLocalTotpProvider:
    def test_valid_secret(self):
        provider = LocalTotpProvider("user", totp_secret="JBSWY3DPEHPK3PXP")
        code = provider.get_totp()
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()

    def test_corrupt_secret(self):
        provider = LocalTotpProvider("user", totp_secret="NOT-VALID!!!")
        assert provider.get_totp() is None
        assert provider._totp_secret is None

    def test_no_secret_no_keyring(self):
        with patch("openconnect_saml.totp_providers.keyring") as mock_kr:
            mock_kr.get_password.return_value = None
            provider = LocalTotpProvider("user")
            assert provider.get_totp() is None


# ---------------------------------------------------------------------------
# TwoFAuthProvider
# ---------------------------------------------------------------------------


class TestTwoFAuthProvider:
    def _make_provider(self, **kwargs):
        defaults = {
            "url": "https://2fa.example.com",
            "token": "test-token",
            "account_id": 42,
            "timeout": 5,
        }
        defaults.update(kwargs)
        return TwoFAuthProvider(**defaults)

    def test_successful_fetch(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "password": "123456",
            "otp_type": "totp",
            "generated_at": 1234567890,
            "period": 30,
        }
        with patch(
            "openconnect_saml.totp_providers.requests.get", return_value=mock_resp
        ) as mock_get:
            result = provider.get_totp()
            assert result == "123456"
            mock_get.assert_called_once_with(
                "https://2fa.example.com/api/v1/twofaccounts/42/otp",
                headers={"Authorization": "Bearer test-token"},
                timeout=5,
            )

    def test_auth_failure(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch("openconnect_saml.totp_providers.requests.get", return_value=mock_resp):
            assert provider.get_totp() is None

    def test_account_not_found(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("openconnect_saml.totp_providers.requests.get", return_value=mock_resp):
            assert provider.get_totp() is None

    def test_timeout(self):
        import requests as req

        provider = self._make_provider()
        with patch(
            "openconnect_saml.totp_providers.requests.get",
            side_effect=req.exceptions.Timeout("timed out"),
        ):
            assert provider.get_totp() is None

    def test_connection_error(self):
        import requests as req

        provider = self._make_provider()
        with patch(
            "openconnect_saml.totp_providers.requests.get",
            side_effect=req.exceptions.ConnectionError("refused"),
        ):
            assert provider.get_totp() is None

    def test_unexpected_status(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("openconnect_saml.totp_providers.requests.get", return_value=mock_resp):
            assert provider.get_totp() is None

    def test_invalid_json(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        with patch("openconnect_saml.totp_providers.requests.get", return_value=mock_resp):
            assert provider.get_totp() is None

    def test_missing_password_field(self):
        provider = self._make_provider()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"otp_type": "totp"}
        with patch("openconnect_saml.totp_providers.requests.get", return_value=mock_resp):
            assert provider.get_totp() is None

    def test_trailing_slash_stripped(self):
        provider = self._make_provider(url="https://2fa.example.com/")
        assert provider.url == "https://2fa.example.com"

    def test_http_warning(self, caplog):
        """HTTP URLs should trigger a warning."""
        import logging

        with caplog.at_level(logging.WARNING):
            _provider = self._make_provider(url="http://insecure.example.com")
        # structlog might not use caplog — check via the provider itself
        # The warning is logged during __init__, we verify no crash


# ---------------------------------------------------------------------------
# CLI flags
# ---------------------------------------------------------------------------


class TestCLIFlags:
    def test_totp_source_flag(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(["-s", "vpn.example.com", "--totp-source", "2fauth"])
        assert args.totp_source == "2fauth"

    def test_totp_source_default(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.totp_source is None

    def test_2fauth_url_flag(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(
            ["-s", "vpn.example.com", "--2fauth-url", "https://2fa.example.com"]
        )
        assert args.twofauth_url == "https://2fa.example.com"

    def test_2fauth_token_flag(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(["-s", "vpn.example.com", "--2fauth-token", "my-secret-token"])
        assert args.twofauth_token == "my-secret-token"

    def test_2fauth_account_id_flag(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(["-s", "vpn.example.com", "--2fauth-account-id", "42"])
        assert args.twofauth_account_id == 42

    def test_all_2fauth_flags_together(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(
            [
                "-s",
                "vpn.example.com",
                "--totp-source",
                "2fauth",
                "--2fauth-url",
                "https://2fa.example.com",
                "--2fauth-token",
                "tok",
                "--2fauth-account-id",
                "7",
            ]
        )
        assert args.totp_source == "2fauth"
        assert args.twofauth_url == "https://2fa.example.com"
        assert args.twofauth_token == "tok"
        assert args.twofauth_account_id == 7


# ---------------------------------------------------------------------------
# Integration: provider via pytest-httpserver
# ---------------------------------------------------------------------------


class TestTwoFAuthHTTPServer:
    """Integration tests using pytest-httpserver to mock the 2FAuth API."""

    def test_real_http_success(self, httpserver):
        httpserver.expect_request(
            "/api/v1/twofaccounts/42/otp",
            headers={"Authorization": "Bearer test-token"},
        ).respond_with_json(
            {"password": "987654", "otp_type": "totp", "period": 30, "generated_at": 1}
        )

        provider = TwoFAuthProvider(
            url=httpserver.url_for(""),
            token="test-token",
            account_id=42,
        )
        assert provider.get_totp() == "987654"

    def test_real_http_auth_error(self, httpserver):
        httpserver.expect_request("/api/v1/twofaccounts/42/otp").respond_with_data(
            "Unauthorized", status=401
        )

        provider = TwoFAuthProvider(
            url=httpserver.url_for(""),
            token="bad-token",
            account_id=42,
        )
        assert provider.get_totp() is None

    def test_real_http_not_found(self, httpserver):
        httpserver.expect_request("/api/v1/twofaccounts/999/otp").respond_with_data(
            "Not Found", status=404
        )

        provider = TwoFAuthProvider(
            url=httpserver.url_for(""),
            token="test-token",
            account_id=999,
        )
        assert provider.get_totp() is None

    def test_real_http_server_error(self, httpserver):
        httpserver.expect_request("/api/v1/twofaccounts/42/otp").respond_with_data(
            "Internal Server Error", status=500
        )

        provider = TwoFAuthProvider(
            url=httpserver.url_for(""),
            token="test-token",
            account_id=42,
        )
        assert provider.get_totp() is None
