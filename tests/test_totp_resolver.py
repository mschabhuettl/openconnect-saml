"""Tests for the TOTP-source resolver and provider configurator."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openconnect_saml.app import configure_totp_provider, resolve_totp_source
from openconnect_saml.config import (
    BitwardenConfig,
    Config,
    Credentials,
    OnePasswordConfig,
    PassConfig,
    TwoFAuthConfig,
)


def _args(**kwargs):
    defaults = {
        "no_totp": False,
        "totp_source": None,
        "bw_item_id": None,
        "op_item": None,
        "op_vault": None,
        "op_account": None,
        "pass_entry": None,
        "twofauth_url": None,
        "twofauth_token": None,
        "twofauth_account_id": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestResolveTotpSource:
    def test_no_totp_flag_wins(self):
        creds = Credentials("u@x.test", totp_source="local")
        assert resolve_totp_source(_args(no_totp=True, totp_source="bitwarden"), creds) == "none"

    def test_cli_flag_wins_over_credentials(self):
        creds = Credentials("u@x.test", totp_source="local")
        assert resolve_totp_source(_args(totp_source="bitwarden"), creds) == "bitwarden"

    def test_falls_back_to_credentials(self):
        creds = Credentials("u@x.test", totp_source="1password")
        assert resolve_totp_source(_args(), creds) == "1password"

    def test_falls_back_to_local_without_credentials(self):
        assert resolve_totp_source(_args(), None) == "local"


class TestConfigureTotpProvider:
    def test_none_disables_prompt(self):
        cfg = Config()
        creds = Credentials("u@x.test")
        configure_totp_provider(_args(no_totp=True), cfg, creds)
        assert creds.totp_source == "none"

    def test_bitwarden_requires_item_id(self):
        cfg = Config()
        creds = Credentials("u@x.test")
        with pytest.raises(ValueError) as info:
            configure_totp_provider(_args(totp_source="bitwarden"), cfg, creds)
        assert info.value.args[1] == 22

    def test_bitwarden_uses_cli_item_id(self, monkeypatch):
        cfg = Config()
        creds = Credentials("u@x.test")
        # Stub out the actual provider to avoid a `bw` invocation
        called = {}

        class FakeProvider:
            def __init__(self, item_id):
                called["item_id"] = item_id

        monkeypatch.setattr("openconnect_saml.app.BitwardenProvider", FakeProvider)
        configure_totp_provider(_args(totp_source="bitwarden", bw_item_id="abc-123"), cfg, creds)
        assert called["item_id"] == "abc-123"
        assert isinstance(cfg.bitwarden, BitwardenConfig)
        assert cfg.bitwarden.item_id == "abc-123"
        assert creds.totp_source == "bitwarden"

    def test_bitwarden_uses_config_item_id_as_fallback(self, monkeypatch):
        cfg = Config(bitwarden=BitwardenConfig(item_id="cfg-uuid"))
        creds = Credentials("u@x.test")
        monkeypatch.setattr(
            "openconnect_saml.app.BitwardenProvider", MagicMock(return_value=MagicMock())
        )
        configure_totp_provider(_args(totp_source="bitwarden"), cfg, creds)
        # No CLI flag, but config has it → no error
        assert creds.totp_source == "bitwarden"

    def test_onepassword_requires_item(self):
        cfg = Config()
        creds = Credentials("u@x.test")
        with pytest.raises(ValueError) as info:
            configure_totp_provider(_args(totp_source="1password"), cfg, creds)
        assert info.value.args[1] == 23

    def test_onepassword_with_cli_item(self, monkeypatch):
        cfg = Config()
        creds = Credentials("u@x.test")
        monkeypatch.setattr(
            "openconnect_saml.app.OnePasswordProvider", MagicMock(return_value=MagicMock())
        )
        configure_totp_provider(_args(totp_source="1password", op_item="vpn-item"), cfg, creds)
        assert isinstance(cfg.onepassword, OnePasswordConfig)
        assert cfg.onepassword.item == "vpn-item"

    def test_pass_requires_entry(self):
        cfg = Config()
        creds = Credentials("u@x.test")
        with pytest.raises(ValueError) as info:
            configure_totp_provider(_args(totp_source="pass"), cfg, creds)
        assert info.value.args[1] == 24

    def test_pass_with_cli_entry(self, monkeypatch):
        cfg = Config()
        creds = Credentials("u@x.test")
        monkeypatch.setattr(
            "openconnect_saml.app.PassProvider", MagicMock(return_value=MagicMock())
        )
        configure_totp_provider(_args(totp_source="pass", pass_entry="vpn/totp"), cfg, creds)
        assert isinstance(cfg.pass_, PassConfig)
        assert cfg.pass_.entry == "vpn/totp"

    def test_twofauth_requires_all_three_fields(self):
        cfg = Config()
        creds = Credentials("u@x.test")
        with pytest.raises(ValueError) as info:
            configure_totp_provider(
                _args(totp_source="2fauth", twofauth_url="https://2fa", twofauth_token="t"),
                cfg,
                creds,
            )
        assert info.value.args[1] == 21

    def test_twofauth_with_full_config(self, monkeypatch):
        cfg = Config()
        creds = Credentials("u@x.test")
        monkeypatch.setattr(
            "openconnect_saml.app.TwoFAuthProvider", MagicMock(return_value=MagicMock())
        )
        configure_totp_provider(
            _args(
                totp_source="2fauth",
                twofauth_url="https://2fa.example.com",
                twofauth_token="tok",
                twofauth_account_id=42,
            ),
            cfg,
            creds,
        )
        assert isinstance(cfg.twofauth, TwoFAuthConfig)
        assert cfg.twofauth.account_id == 42

    def test_no_credentials_is_noop(self):
        cfg = Config()
        # No creds → function should silently return without raising even with
        # a provider selected (real flow guarded earlier in _run)
        configure_totp_provider(_args(totp_source="bitwarden"), cfg, None)
        assert cfg.bitwarden is None
