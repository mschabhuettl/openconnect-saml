"""Tests for the Chrome/Playwright browser backend."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestChromeBrowser:
    """Tests for ChromeBrowser class."""

    def test_import(self):
        """Chrome browser module is importable."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        assert ChromeBrowser is not None

    def test_init_defaults(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser()
        assert browser.headless is True
        assert browser.proxy is None
        assert browser.timeout == 60_000
        assert browser.cookies == {}
        assert browser.url is None

    def test_init_custom(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser(headless=False, proxy="http://proxy:8080", timeout=30_000)
        assert browser.headless is False
        assert browser.proxy == "http://proxy:8080"
        assert browser.timeout == 30_000

    def test_url_matches(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        assert ChromeBrowser._url_matches(
            "https://login.example.com/saml", "https://login.example.com/saml"
        )
        assert ChromeBrowser._url_matches(
            "https://login.example.com/saml?foo=bar", "https://login.example.com/saml"
        )
        assert not ChromeBrowser._url_matches(
            "https://login.example.com/saml", "https://other.example.com/saml"
        )
        assert not ChromeBrowser._url_matches(
            "https://login.example.com/saml", "https://login.example.com/other"
        )

    @patch("openconnect_saml.browser.chrome.ChromeBrowser.spawn", new_callable=AsyncMock)
    @patch("openconnect_saml.browser.chrome.ChromeBrowser.close", new_callable=AsyncMock)
    def test_context_manager(self, mock_close, mock_spawn):
        from openconnect_saml.browser.chrome import ChromeBrowser

        async def _test():
            async with ChromeBrowser() as browser:
                assert browser is not None
            mock_spawn.assert_called_once()
            mock_close.assert_called_once()

        asyncio.run(_test())

    def test_spawn_without_playwright_raises(self):
        """Spawn raises ImportError when playwright is not installed."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser()

        async def _test():
            # Mock the import inside spawn to simulate missing playwright
            with (
                patch(
                    "openconnect_saml.browser.chrome.ChromeBrowser.spawn",
                    new_callable=AsyncMock,
                    side_effect=ImportError("Playwright is not installed"),
                ),
                pytest.raises(ImportError, match="Playwright is not installed"),
            ):
                await browser.spawn()

        asyncio.run(_test())

    def test_authenticate_at_without_spawn_raises(self):
        """authenticate_at raises RuntimeError if browser not started."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser()

        async def _test():
            with pytest.raises(RuntimeError, match="Browser not started"):
                await browser.authenticate_at("https://example.com")

        asyncio.run(_test())

    @patch("openconnect_saml.browser.chrome.ChromeBrowser.spawn", new_callable=AsyncMock)
    def test_auto_fill_selectors_defined(self, _):
        """Verify auto-fill selector lists are non-empty."""
        from openconnect_saml.browser.chrome import (
            _CLICK_SELECTORS,
            _PASSWORD_SELECTORS,
            _SUBMIT_SELECTORS,
            _TOTP_SELECTORS,
            _USERNAME_SELECTORS,
        )

        assert len(_USERNAME_SELECTORS) > 0
        assert len(_PASSWORD_SELECTORS) > 0
        assert len(_TOTP_SELECTORS) > 0
        assert len(_SUBMIT_SELECTORS) > 0
        assert len(_CLICK_SELECTORS) > 0


class TestChromeBrowserIntegration:
    """Integration-style tests with mocked Playwright."""

    def _make_mock_page(self):
        page = AsyncMock()
        page.url = "https://login.example.com/saml"
        page.goto = AsyncMock()
        page.wait_for_load_state = AsyncMock()
        page.wait_for_url = AsyncMock()

        locator = AsyncMock()
        locator.is_visible = AsyncMock(return_value=False)
        locator.input_value = AsyncMock(return_value="")
        locator.fill = AsyncMock()
        locator.click = AsyncMock()
        locator.first = locator

        page.locator = MagicMock(return_value=locator)
        return page

    def _make_mock_context(self, cookies=None):
        context = AsyncMock()
        context.cookies = AsyncMock(return_value=cookies or [])
        context.new_page = AsyncMock()
        return context

    def test_authenticate_at_finds_cookie(self):
        """authenticate_at returns cookies when SSO token is found."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser()
        page = self._make_mock_page()
        # After first step, URL changes to final
        page.url = "https://login.example.com/done"

        context = self._make_mock_context(
            cookies=[
                {"name": "sso_token", "value": "abc123"},
                {"name": "session", "value": "xyz"},
            ]
        )
        context.new_page = AsyncMock(return_value=page)

        browser._page = page
        browser._context = context

        async def _test():
            cookies = await browser.authenticate_at(
                url="https://login.example.com/saml",
                final_url="https://login.example.com/done",
                token_cookie_name="sso_token",
            )
            assert cookies["sso_token"] == "abc123"

        asyncio.run(_test())

    def test_authenticate_at_reaches_final_url(self):
        """authenticate_at stops when final URL is reached."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser()
        page = self._make_mock_page()
        page.url = "https://vpn.example.com/final"

        context = self._make_mock_context(cookies=[{"name": "token", "value": "t1"}])
        context.new_page = AsyncMock(return_value=page)

        browser._page = page
        browser._context = context

        async def _test():
            cookies = await browser.authenticate_at(
                url="https://login.example.com/saml",
                final_url="https://vpn.example.com/final",
            )
            assert "token" in cookies

        asyncio.run(_test())
