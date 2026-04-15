"""Tests for community-fixes-r2 features."""

from unittest.mock import MagicMock, patch

from openconnect_saml.authenticator import (
    Authenticator,
    SSLLegacyAdapter,
    UnexpectedResponse,
    create_http_session,
    parse_response,
)
from openconnect_saml.config import Config, Credentials, HostProfile

# --- SSL Legacy (#81) ---


def test_create_http_session_without_ssl_legacy():
    session = create_http_session(None, "4.7.00136", ssl_legacy=False)
    # Should not have our custom adapter
    adapter = session.get_adapter("https://example.com")
    assert not isinstance(adapter, SSLLegacyAdapter)


def test_create_http_session_with_ssl_legacy():
    session = create_http_session(None, "4.7.00136", ssl_legacy=True)
    adapter = session.get_adapter("https://example.com")
    assert isinstance(adapter, SSLLegacyAdapter)


def test_detect_authentication_target_url_uses_plain_probe_session():
    """Cisco entry hosts may reject the AnyConnect-header session GET with 404."""
    host = HostProfile("https://vpn.example.com/group", "", "")
    original_url = host.vpn_url
    auth = Authenticator(host, version="4.7.00136")

    redirected_response = MagicMock()
    redirected_response.url = "https://entry29-vpn.example.com/group"
    redirected_response.raise_for_status.return_value = None

    probe_session = MagicMock()
    probe_session.get.return_value = redirected_response

    with (
        patch.object(
            auth.session,
            "get",
            side_effect=AssertionError("redirect probe should not use the auth session"),
        ),
        patch("openconnect_saml.authenticator.requests.Session", return_value=probe_session),
    ):
        auth._detect_authentication_target_url()

    probe_session.get.assert_called_once_with(original_url, timeout=auth.timeout)
    assert auth.host.address == redirected_response.url


# --- TOTP binascii.Error (#143) ---


def test_totp_with_corrupt_secret_in_memory():
    """Corrupt TOTP secret should return None, not crash."""
    cred = Credentials("testuser")
    cred._totp_secret = "NOT-VALID-BASE32!!!"
    result = cred.totp
    assert result is None
    # The secret should be cleared
    assert cred._totp_secret is None


def test_totp_with_valid_secret():
    """Valid TOTP secret should return a code."""
    cred = Credentials("testuser")
    cred._totp_secret = "JBSWY3DPEHPK3PXP"  # valid base32
    result = cred.totp
    assert result is not None
    assert len(result) == 6
    assert result.isdigit()


@patch("openconnect_saml.config.keyring")
def test_totp_with_corrupt_secret_in_keyring(mock_keyring):
    """Corrupt TOTP secret from keyring should return None."""
    mock_keyring.get_password.return_value = "CORRUPT!!!"
    mock_keyring.errors = MagicMock()
    mock_keyring.errors.KeyringError = Exception
    cred = Credentials("testuser")
    result = cred.totp
    assert result is None


# --- Invalid response type (#121) ---


def test_parse_response_unknown_type():
    """Unknown response type should return UnexpectedResponse, not None."""
    xml_content = b'<?xml version="1.0" encoding="UTF-8"?><config-auth type="unknown-type"><auth id="main"/></config-auth>'
    resp = MagicMock()
    resp.content = xml_content
    resp.raise_for_status = MagicMock()
    result = parse_response(resp)
    assert isinstance(result, UnexpectedResponse)
    assert result.response_type == "unknown-type"


def test_parse_response_none_type():
    """Response with no type attribute should return UnexpectedResponse."""
    xml_content = (
        b'<?xml version="1.0" encoding="UTF-8"?><config-auth><auth id="main"/></config-auth>'
    )
    resp = MagicMock()
    resp.content = xml_content
    resp.raise_for_status = MagicMock()
    result = parse_response(resp)
    assert isinstance(result, UnexpectedResponse)
    assert result.response_type is None


# --- Configurable timeout ---


def test_config_default_timeout():
    cfg = Config()
    assert cfg.timeout == 30


def test_config_custom_timeout():
    cfg = Config.from_dict({"timeout": 60})
    assert cfg.timeout == 60


# --- Window size config ---


def test_config_default_window_size():
    cfg = Config()
    assert cfg.window_width == 800
    assert cfg.window_height == 600


def test_config_custom_window_size():
    cfg = Config.from_dict({"window_width": 1000, "window_height": 800})
    assert cfg.window_width == 1000
    assert cfg.window_height == 800


# --- on_connect config ---


def test_config_default_on_connect():
    cfg = Config()
    assert cfg.on_connect == ""


def test_config_on_connect():
    cfg = Config.from_dict({"on_connect": "/usr/local/bin/vpn-up.sh"})
    assert cfg.on_connect == "/usr/local/bin/vpn-up.sh"
