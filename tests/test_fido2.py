"""Tests for FIDO2/WebAuthn authentication support."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest

from openconnect_saml.fido2_auth import (
    DEFAULT_FIDO2_TIMEOUT,
    FIDO2Authenticator,
    FIDO2AuthError,
    create_fido2_js_bridge,
    handle_fido2_challenge_headless,
)


class TestFIDO2Authenticator:
    def test_init_defaults(self):
        auth = FIDO2Authenticator()
        assert auth.timeout == DEFAULT_FIDO2_TIMEOUT
        assert auth._client is None
        assert auth._device is None

    def test_init_custom_timeout(self):
        auth = FIDO2Authenticator(timeout=60)
        assert auth.timeout == 60

    def test_detect_device_no_fido2_library(self):
        """detect_device raises FIDO2AuthError when library not installed."""
        auth = FIDO2Authenticator()

        # Intercept the import so the test works whether fido2 is installed or not.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "fido2" or name.startswith("fido2."):
                raise ImportError(f"No module named '{name}'")
            return real_import(name, *args, **kwargs)

        with (
            patch.object(builtins, "__import__", side_effect=fake_import),
            pytest.raises(FIDO2AuthError, match="not installed"),
        ):
            auth._ensure_fido2()

    @patch("openconnect_saml.fido2_auth.FIDO2Authenticator._ensure_fido2")
    def test_detect_device_none_found(self, mock_ensure):
        """detect_device returns False when no devices connected."""
        mock_ctap = MagicMock()
        mock_ctap.list_devices.return_value = []
        mock_ensure.return_value = mock_ctap

        auth = FIDO2Authenticator()
        assert auth.detect_device() is False
        assert auth._device is None

    @patch("openconnect_saml.fido2_auth.FIDO2Authenticator._ensure_fido2")
    def test_detect_device_found(self, mock_ensure):
        """detect_device returns True and stores device when found."""
        mock_device = MagicMock()
        mock_ctap = MagicMock()
        mock_ctap.list_devices.return_value = [mock_device]
        mock_ensure.return_value = mock_ctap

        auth = FIDO2Authenticator()
        assert auth.detect_device() is True
        assert auth._device is mock_device

    def test_close_without_device(self):
        """close() doesn't raise when no device is set."""
        auth = FIDO2Authenticator()
        auth.close()  # Should not raise

    def test_close_with_device(self):
        """close() closes the device."""
        auth = FIDO2Authenticator()
        mock_device = MagicMock()
        auth._device = mock_device

        auth.close()
        mock_device.close.assert_called_once()
        assert auth._device is None

    def test_close_device_error_suppressed(self):
        """close() suppresses errors from device.close()."""
        auth = FIDO2Authenticator()
        mock_device = MagicMock()
        mock_device.close.side_effect = OSError("device error")
        auth._device = mock_device

        auth.close()  # Should not raise
        assert auth._device is None


class TestFIDO2JSBridge:
    def test_js_bridge_content(self):
        """JS bridge contains expected WebAuthn override code."""
        js = create_fido2_js_bridge(FIDO2Authenticator())
        assert "navigator.credentials.get" in js
        assert "openconnect-fido2-request" in js
        assert "openconnect-fido2-response" in js
        assert "FIDO2 bridge installed" in js

    def test_js_bridge_is_iife(self):
        """JS bridge is wrapped in an IIFE."""
        js = create_fido2_js_bridge(FIDO2Authenticator())
        stripped = js.strip()
        assert stripped.startswith("(function()")
        assert stripped.endswith("})();")


class TestHandleFIDO2ChallengeHeadless:
    @patch("openconnect_saml.fido2_auth.FIDO2Authenticator.authenticate")
    def test_headless_challenge_response(self, mock_auth):
        """handle_fido2_challenge_headless returns base64-encoded response."""
        mock_auth.return_value = {
            "authenticatorData": b"\x01\x02\x03",
            "clientDataJSON": b"\x04\x05\x06",
            "signature": b"\x07\x08\x09",
            "credentialId": b"\x0a\x0b\x0c",
        }

        auth = FIDO2Authenticator()
        challenge_data = {
            "challenge": base64.urlsafe_b64encode(b"test-challenge").decode().rstrip("="),
            "rpId": "example.com",
            "allowCredentials": [
                {
                    "type": "public-key",
                    "id": base64.urlsafe_b64encode(b"cred1").decode().rstrip("="),
                }
            ],
            "userVerification": "discouraged",
        }

        result = handle_fido2_challenge_headless(auth, challenge_data)

        assert "authenticatorData" in result
        assert "clientDataJSON" in result
        assert "signature" in result
        assert "credentialId" in result

        # Verify base64 encoding
        decoded = base64.urlsafe_b64decode(result["authenticatorData"] + "==")
        assert decoded == b"\x01\x02\x03"

    @patch("openconnect_saml.fido2_auth.FIDO2Authenticator.authenticate")
    def test_headless_challenge_without_credentials(self, mock_auth):
        """Works without allowCredentials."""
        mock_auth.return_value = {
            "authenticatorData": b"\x01",
            "clientDataJSON": b"\x02",
            "signature": b"\x03",
            "credentialId": b"\x04",
        }

        auth = FIDO2Authenticator()
        challenge_data = {
            "challenge": base64.urlsafe_b64encode(b"challenge").decode().rstrip("="),
            "rpId": "example.com",
        }

        result = handle_fido2_challenge_headless(auth, challenge_data)
        assert "signature" in result
        mock_auth.assert_called_once()
        # Verify credential_ids is None when not provided
        call_kwargs = mock_auth.call_args[1]
        assert call_kwargs["credential_ids"] is None


class TestFIDO2ConfigIntegration:
    def test_fido2_action_type_in_config(self):
        """Verify 'fido2' is a recognized auto-fill action type."""
        from openconnect_saml.config import AUTOFILL_ACTIONS

        assert "fido2" in AUTOFILL_ACTIONS

    def test_autofill_rule_with_fido2_action(self):
        """AutoFillRule accepts 'fido2' as an action."""
        from openconnect_saml.config import AutoFillRule

        rule = AutoFillRule(selector="div.fido2-challenge", action="fido2")
        assert rule.action == "fido2"
        assert rule.selector == "div.fido2-challenge"
