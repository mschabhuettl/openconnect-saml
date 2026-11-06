"""Tests for the Chrome/Playwright browser backend."""

from __future__ import annotations

import asyncio
import importlib.util
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Some tests below patch ``playwright.async_api.async_playwright`` and call
# ``spawn()``, which means Python actually imports the module. ``playwright``
# is an optional extra (``pip install openconnect-saml[chrome]``) and is not
# in the default ``[dev]`` install used by CI, so those tests have to skip
# when the module isn't there.
_PLAYWRIGHT_INSTALLED = importlib.util.find_spec("playwright") is not None
_skip_no_playwright = pytest.mark.skipif(
    not _PLAYWRIGHT_INSTALLED,
    reason="playwright not installed; spawn() can't be exercised without the import target",
)


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
        assert browser.channel is None
        assert browser.cookies == {}
        assert browser.url is None

    def test_init_custom(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser(
            headless=False,
            proxy="http://proxy:8080",
            timeout=30_000,
            channel="chrome",
        )
        assert browser.headless is False
        assert browser.proxy == "http://proxy:8080"
        assert browser.timeout == 30_000
        assert browser.channel == "chrome"

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

    @_skip_no_playwright
    def test_channel_propagates_to_launch_args(self):
        """When ``channel`` is set, Playwright's launch() must receive it
        so it picks the system Chrome/Edge instead of bundled Chromium."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        async def _test():
            browser = ChromeBrowser(channel="chrome")

            mock_chromium = MagicMock()
            mock_chromium.launch = AsyncMock()
            mock_chromium.launch.return_value.new_context.return_value.new_page.return_value.set_default_timeout = MagicMock()
            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium
            mock_pw.stop = AsyncMock()
            mock_async_pw = MagicMock()
            mock_async_pw.start = AsyncMock(return_value=mock_pw)

            with patch("playwright.async_api.async_playwright", return_value=mock_async_pw):
                await browser.spawn()

            # The launch() call must have received channel="chrome".
            launch_kwargs = mock_chromium.launch.call_args.kwargs
            assert launch_kwargs.get("channel") == "chrome"
            assert launch_kwargs["chromium_sandbox"] is True

        asyncio.run(_test())

    @_skip_no_playwright
    def test_no_channel_means_no_channel_arg(self):
        """When ``channel`` is None (default), Playwright's launch() must
        NOT receive a ``channel`` kwarg — otherwise we'd accidentally
        pin to a non-existent channel."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        async def _test():
            browser = ChromeBrowser()  # channel defaults to None

            mock_chromium = MagicMock()
            mock_chromium.launch = AsyncMock()
            mock_chromium.launch.return_value.new_context.return_value.new_page.return_value.set_default_timeout = MagicMock()
            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium
            mock_pw.stop = AsyncMock()
            mock_async_pw = MagicMock()
            mock_async_pw.start = AsyncMock(return_value=mock_pw)

            with patch("playwright.async_api.async_playwright", return_value=mock_async_pw):
                await browser.spawn()

            launch_kwargs = mock_chromium.launch.call_args.kwargs
            assert "channel" not in launch_kwargs

        asyncio.run(_test())

    def test_init_executable_path(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser(executable_path="/usr/bin/chromium")
        assert browser.executable_path == "/usr/bin/chromium"
        # Default stays None so we never accidentally pin a binary.
        assert ChromeBrowser().executable_path is None

    @_skip_no_playwright
    def test_executable_path_propagates_to_launch_args(self, tmp_path):
        """When ``executable_path`` is set, Playwright's launch() must
        receive it so a plain distro chromium can be driven directly (#39)."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        fake_bin = tmp_path / "chromium"
        fake_bin.write_text("#!/bin/sh\n")

        async def _test():
            browser = ChromeBrowser(executable_path=str(fake_bin))

            mock_chromium = MagicMock()
            mock_chromium.launch = AsyncMock()
            mock_chromium.launch.return_value.new_context.return_value.new_page.return_value.set_default_timeout = MagicMock()
            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium
            mock_pw.stop = AsyncMock()
            mock_async_pw = MagicMock()
            mock_async_pw.start = AsyncMock(return_value=mock_pw)

            with patch("playwright.async_api.async_playwright", return_value=mock_async_pw):
                await browser.spawn()

            launch_kwargs = mock_chromium.launch.call_args.kwargs
            assert launch_kwargs.get("executable_path") == str(fake_bin)

        asyncio.run(_test())

    @_skip_no_playwright
    def test_executable_path_wins_over_channel(self, tmp_path):
        """executable_path and channel are mutually exclusive in Playwright;
        an explicit executable must win and channel must be dropped."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        fake_bin = tmp_path / "chromium"
        fake_bin.write_text("#!/bin/sh\n")

        async def _test():
            browser = ChromeBrowser(executable_path=str(fake_bin), channel="chrome")

            mock_chromium = MagicMock()
            mock_chromium.launch = AsyncMock()
            mock_chromium.launch.return_value.new_context.return_value.new_page.return_value.set_default_timeout = MagicMock()
            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium
            mock_pw.stop = AsyncMock()
            mock_async_pw = MagicMock()
            mock_async_pw.start = AsyncMock(return_value=mock_pw)

            with patch("playwright.async_api.async_playwright", return_value=mock_async_pw):
                await browser.spawn()

            launch_kwargs = mock_chromium.launch.call_args.kwargs
            assert launch_kwargs.get("executable_path") == str(fake_bin)
            assert "channel" not in launch_kwargs

        asyncio.run(_test())

    @_skip_no_playwright
    def test_executable_path_missing_file_raises(self):
        """A non-existent --chrome-executable path fails early with a clear
        message instead of Playwright's denser error."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        async def _test():
            browser = ChromeBrowser(executable_path="/no/such/chromium-binary")
            with pytest.raises(RuntimeError, match="does not exist"):
                await browser.spawn()
            # No driver process should have been left running.
            assert browser._playwright is None

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
        page.on = MagicMock()
        page.remove_listener = MagicMock()
        page.is_closed = MagicMock(return_value=False)
        page.frames = [page]
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
        context.cookies.side_effect = [[], context.cookies.return_value]

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


@_skip_no_playwright
@pytest.mark.asyncio
async def test_persistent_profile_keeps_extensions_and_closes_context(tmp_path):
    from openconnect_saml.browser.chrome import ChromeBrowser

    page = MagicMock()
    page.is_closed.return_value = False
    page.frames = [page]
    context = AsyncMock()
    context.pages = [page]
    driver = MagicMock()
    driver.chromium.launch_persistent_context = AsyncMock(return_value=context)
    driver.chromium.launch = AsyncMock()
    driver.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=driver)
    profile = tmp_path / "vpn-profile"
    with patch("playwright.async_api.async_playwright", return_value=starter):
        async with ChromeBrowser(user_data_dir=str(profile), channel="chrome", headless=False):
            assert profile.is_dir()
    driver.chromium.launch.assert_not_awaited()
    launch = driver.chromium.launch_persistent_context.call_args
    assert launch.args == (str(profile.resolve()),)
    assert launch.kwargs["channel"] == "chrome"
    assert launch.kwargs["chromium_sandbox"] is True
    assert set(launch.kwargs["ignore_default_args"]) == {
        "--disable-extensions",
        "--use-mock-keychain",
        "--password-store=basic",
    }
    context.new_page.assert_not_awaited()
    context.close.assert_awaited_once()
    driver.stop.assert_awaited_once()


@_skip_no_playwright
@pytest.mark.asyncio
async def test_profile_launch_failure_stops_driver(tmp_path):
    from openconnect_saml.browser.chrome import ChromeBrowser

    driver = MagicMock()
    driver.chromium.launch_persistent_context = AsyncMock(
        side_effect=RuntimeError("profile locked")
    )
    driver.stop = AsyncMock()
    starter = MagicMock()
    starter.start = AsyncMock(return_value=driver)
    with (
        patch("playwright.async_api.async_playwright", return_value=starter),
        pytest.raises(RuntimeError, match="profile locked"),
    ):
        await ChromeBrowser(user_data_dir=str(tmp_path)).spawn()
    driver.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_saved_sso_completion_cookie_is_cleared_before_new_login():
    from openconnect_saml.browser.chrome import ChromeBrowser

    browser = ChromeBrowser()
    page = MagicMock()
    page.is_closed.return_value = False
    page.frames = [page]
    page.url = "https://vpn.example.com/final"
    page.goto = AsyncMock()
    context = AsyncMock()
    old = {"name": "sso", "value": "old", "domain": "vpn.example.com", "path": "/"}
    fresh = {**old, "value": "fresh"}
    context.cookies.side_effect = [[old], [fresh]]
    browser._page, browser._context = page, context
    await browser.authenticate_at(
        "https://vpn.example.com/login", final_url=page.url, token_cookie_name="sso"
    )
    context.clear_cookies.assert_awaited_once_with(name="sso", domain="vpn.example.com", path="/")
    assert all(call.args == (page.url,) for call in context.cookies.call_args_list)
    assert browser.cookies == {"sso": "fresh"}


@pytest.mark.asyncio
@pytest.mark.parametrize("username_only", [False, True])
async def test_final_url_waits_for_fresh_cookie_and_username_only_leaves_submission_manual(
    username_only,
):
    from types import SimpleNamespace

    from openconnect_saml.browser.chrome import ChromeBrowser

    browser = ChromeBrowser()
    page = MagicMock()
    page.is_closed.return_value = False
    page.frames = [page]
    page.url = "https://vpn.example.com/final"
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_url = AsyncMock()
    context = AsyncMock()
    context.cookies.side_effect = [[], [], [{"name": "sso", "value": "fresh"}]]
    browser._page, browser._context = page, context
    browser._auto_fill = AsyncMock(return_value=True)
    browser._detect_mfa_challenge = AsyncMock()
    browser._try_click_selectors = AsyncMock()
    credentials = SimpleNamespace(username_only=username_only)
    with patch("openconnect_saml.browser.chrome.asyncio.sleep", new_callable=AsyncMock):
        cookies = await browser.authenticate_at(
            "https://vpn.example.com/login",
            credentials=credentials,
            final_url=page.url,
            token_cookie_name="sso",
        )
    assert cookies == {"sso": "fresh"}
    selectors = browser._try_click_selectors.call_args.args[0]
    assert bool(selectors) is not username_only
    context.clear_cookies.assert_not_awaited()
    assert all(call.args == (page.url,) for call in context.cookies.call_args_list)
