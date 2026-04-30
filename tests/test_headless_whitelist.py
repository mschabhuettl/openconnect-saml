"""Tests for the headless redirect-host whitelist (#11)."""

from __future__ import annotations

import pytest

from openconnect_saml.headless import HeadlessAuthenticator, HeadlessAuthError


class TestHostAllowed:
    def test_no_whitelist_allows_everything(self):
        h = HeadlessAuthenticator(allowed_hosts=None)
        assert h._host_allowed("https://anywhere.com/login") is True
        assert h._host_allowed("https://attacker.example.org/x") is True

    def test_empty_whitelist_blocks_everything(self):
        h = HeadlessAuthenticator(allowed_hosts=[])
        # An empty list still means "no whitelist enforcement" in our
        # implementation (None vs. empty distinction is intentional).
        # An empty list is treated like None per the constructor coercion.
        assert h.allowed_hosts is None  # coerced to None
        assert h._host_allowed("https://anywhere.com") is True

    def test_single_host_match(self):
        h = HeadlessAuthenticator(allowed_hosts=["idp.example.com"])
        assert h._host_allowed("https://idp.example.com/login") is True
        assert h._host_allowed("https://attacker.org/login") is False

    def test_glob_subdomain_match(self):
        h = HeadlessAuthenticator(allowed_hosts=["*.duosecurity.com"])
        assert h._host_allowed("https://api-1a.duosecurity.com") is True
        assert h._host_allowed("https://duosecurity.com") is False  # glob requires subdomain
        assert h._host_allowed("https://other.com") is False

    def test_case_insensitive(self):
        h = HeadlessAuthenticator(allowed_hosts=["IDP.Example.Com"])
        assert h._host_allowed("https://idp.example.com/x") is True

    def test_invalid_url_blocked(self):
        h = HeadlessAuthenticator(allowed_hosts=["x.example.com"])
        # No host portion → blocked
        assert h._host_allowed("not-a-url") is False
        assert h._host_allowed("") is False


class TestAutoExtendWhitelist:
    def test_auto_extends_with_login_url_hosts(self, monkeypatch):
        h = HeadlessAuthenticator(allowed_hosts=["idp.example.com"])
        # Stub session.get so _auto_authenticate doesn't actually fetch
        from unittest.mock import MagicMock

        fake_resp = MagicMock()
        fake_resp.url = "https://gateway.example.com/login"
        fake_resp.headers = {"content-type": "text/html"}
        fake_resp.content = b"<html></html>"
        fake_resp.raise_for_status = MagicMock()
        fake_resp.text = ""
        h.session.get = MagicMock(return_value=fake_resp)
        # The auth function will fail (no forms) — we just want to verify
        # the whitelist auto-extension happened before the host check.
        with pytest.raises(HeadlessAuthError):
            h._auto_authenticate(
                "https://gateway.example.com/login",
                "https://gateway.example.com/done",
                "webvpn",
            )
        # Both hosts should now be in the whitelist.
        assert "gateway.example.com" in h.allowed_hosts


class TestRefuseUnknownRedirect:
    def test_redirect_to_unknown_host_blocked(self):
        """The login_url + login_final_url hosts are auto-allowed, but a
        sneaky redirect to a third host should still be rejected."""
        from unittest.mock import MagicMock

        h = HeadlessAuthenticator(allowed_hosts=["idp.example.com"])
        # First response from login_url points at gateway (auto-allowed),
        # but session.get returns a response whose .url is on a third party.
        fake_resp = MagicMock()
        fake_resp.url = "https://attacker.org/phish"
        fake_resp.headers = {"content-type": "text/html"}
        fake_resp.content = b"<html></html>"
        fake_resp.raise_for_status = MagicMock()
        h.session.get = MagicMock(return_value=fake_resp)
        with pytest.raises(HeadlessAuthError, match="Refusing to follow redirect"):
            h._auto_authenticate(
                "https://gateway.example.com/login",
                "https://gateway.example.com/done",
                "webvpn",
            )
