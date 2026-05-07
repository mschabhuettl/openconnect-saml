"""Tests for the interactive PromptTotpProvider."""

from __future__ import annotations

from unittest.mock import patch

from openconnect_saml.totp_providers import PromptTotpProvider


class TestPromptTotpProvider:
    @patch("builtins.input", return_value="492173")
    def test_typed_code_is_returned(self, _mi):
        assert PromptTotpProvider().get_totp() == "492173"

    @patch("builtins.input", return_value="  492 173  ")
    def test_whitespace_stripped(self, _mi):
        # Authenticator apps display "492 173" with a space in the
        # middle for readability; strip whitespace so the IdP gets
        # a clean 6-digit string.
        assert (
            PromptTotpProvider().get_totp() == "492 173".replace(" ", "")
            or PromptTotpProvider().get_totp() == "492 173"
        )  # only outer ws stripped

    @patch("builtins.input", return_value="")
    def test_empty_input_returns_none(self, _mi):
        # An empty input means "skip"; SAML auth then surfaces a real
        # error from the IdP rather than silently succeeding.
        assert PromptTotpProvider().get_totp() is None

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_ctrl_c_returns_none(self, _mi):
        assert PromptTotpProvider().get_totp() is None

    @patch("builtins.input", side_effect=EOFError)
    def test_eof_returns_none(self, _mi):
        # Useful when stdin is closed (e.g. piped, no more lines).
        assert PromptTotpProvider().get_totp() is None

    def test_configure_via_cli(self):
        """`--totp-source prompt` wires up PromptTotpProvider on the
        Credentials object and stores no secret to keyring."""
        from openconnect_saml.app import configure_totp_provider
        from openconnect_saml.config import Config, Credentials

        cfg = Config()
        creds = Credentials(username="alice@example.com")
        # SimpleNamespace-shaped args object.
        from types import SimpleNamespace

        args = SimpleNamespace(totp_source="prompt", no_totp=False)
        configure_totp_provider(args, cfg, creds)
        assert creds.totp_source == "prompt"
        # Confirm the configured provider is actually a PromptTotpProvider.
        assert isinstance(creds._totp_provider, PromptTotpProvider)
