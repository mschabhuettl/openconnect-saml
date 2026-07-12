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


class TestHelperClickSelectors:
    """MFA-method-switch selectors are gated on TOTP availability (#17)."""

    class _Creds:
        def __init__(self, totp_source="none", totp=None):
            self.totp_source = totp_source
            self._totp = totp

        @property
        def totp(self):
            return self._totp

    def test_no_credentials_drops_totp_switch(self):
        from openconnect_saml.browser import chrome

        selectors = chrome._helper_click_selectors(None)
        assert "div[data-value=PhoneAppOTP]" not in selectors
        assert "a[id=signInAnotherWay]" not in selectors
        assert "input[id=KmsiCheckboxField]" in selectors

    def test_totp_source_none_drops_totp_switch(self):
        from openconnect_saml.browser import chrome

        selectors = chrome._helper_click_selectors(self._Creds(totp_source="none"))
        assert "div[data-value=PhoneAppOTP]" not in selectors
        assert "a[id=signInAnotherWay]" not in selectors

    def test_provider_source_keeps_totp_switch(self):
        from openconnect_saml.browser import chrome

        selectors = chrome._helper_click_selectors(self._Creds(totp_source="1password"))
        assert "div[data-value=PhoneAppOTP]" in selectors
        assert "a[id=signInAnotherWay]" in selectors

    def test_local_source_requires_a_secret(self):
        from openconnect_saml.browser import chrome

        with_secret = chrome._helper_click_selectors(
            self._Creds(totp_source="local", totp="123456")
        )
        without_secret = chrome._helper_click_selectors(self._Creds(totp_source="local"))
        assert "div[data-value=PhoneAppOTP]" in with_secret
        assert "div[data-value=PhoneAppOTP]" not in without_secret

    def test_mfa_remember_checkboxes_always_present(self):
        from openconnect_saml.browser import chrome

        for creds in (None, self._Creds(totp_source="1password")):
            selectors = chrome._helper_click_selectors(creds)
            assert "input[name=DontShowAgain]" in selectors


class _FakeEl:
    """Minimal Playwright element stub for page-logic tests."""

    def __init__(self, visible=False, value="", attrs=None, checked=False):
        self.visible = visible
        self.value = value
        self.attrs = attrs or {}
        self.checked = checked
        self.clicks = 0

    async def is_visible(self, timeout=None):
        return self.visible

    async def input_value(self):
        return self.value

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def is_checked(self):
        return self.checked

    async def click(self):
        self.clicks += 1


class _FakeLocator:
    def __init__(self, el):
        self.first = el


class _FakePage:
    def __init__(self, elements):
        self.elements = elements

    def locator(self, sel):
        return _FakeLocator(self.elements.get(sel, _FakeEl()))


def _browser_with(elements):
    from openconnect_saml.browser.chrome import ChromeBrowser

    browser = ChromeBrowser()
    browser._page = _FakePage(elements)
    return browser


class TestPendingSecret:
    """Submit fires for a pre-filled password screen, but never over an error."""

    def test_filled_visible_password_is_pending(self):
        browser = _browser_with({"input[type=password]": _FakeEl(visible=True, value="s3cret")})
        assert asyncio.run(browser._has_pending_secret()) is True

    def test_empty_password_is_not_pending(self):
        browser = _browser_with({"input[type=password]": _FakeEl(visible=True, value="")})
        assert asyncio.run(browser._has_pending_secret()) is False

    def test_error_banner_blocks_resubmit(self):
        browser = _browser_with(
            {
                "input[type=password]": _FakeEl(visible=True, value="wrong"),
                "div[id=passwordError]": _FakeEl(visible=True),
            }
        )
        assert asyncio.run(browser._has_pending_secret()) is False

    def test_kmsi_page_detected(self):
        browser = _browser_with({"input[id=KmsiCheckboxField]": _FakeEl(visible=True)})
        assert asyncio.run(browser._is_kmsi_page()) is True


class TestCheckboxClick:
    """_try_click_selectors never toggles an already-checked checkbox off."""

    def test_unchecked_checkbox_is_clicked(self):
        el = _FakeEl(visible=True, attrs={"type": "checkbox"}, checked=False)
        browser = _browser_with({"input[name=DontShowAgain]": el})
        clicked = asyncio.run(browser._try_click_selectors(["input[name=DontShowAgain]"]))
        assert clicked is True
        assert el.clicks == 1

    def test_checked_checkbox_is_skipped(self):
        el = _FakeEl(visible=True, attrs={"type": "checkbox"}, checked=True)
        browser = _browser_with({"input[name=DontShowAgain]": el})
        clicked: set[str] = set()
        result = asyncio.run(browser._try_click_selectors(["input[name=DontShowAgain]"], clicked))
        assert result is False
        assert el.clicks == 0
        # Remembered as handled so it isn't re-probed every step.
        assert "input[name=DontShowAgain]" in clicked


class TestPersistentProfile:
    def test_init_default_is_ephemeral(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        assert ChromeBrowser().user_data_dir is None

    def test_init_custom_dir(self):
        from openconnect_saml.browser.chrome import ChromeBrowser

        browser = ChromeBrowser(user_data_dir="/tmp/profile")
        assert browser.user_data_dir == "/tmp/profile"

    @_skip_no_playwright
    def test_spawn_uses_persistent_context(self, tmp_path):
        """With user_data_dir set, Playwright must launch a persistent
        context rooted at that directory instead of an ephemeral one."""
        from openconnect_saml.browser.chrome import ChromeBrowser

        profile_dir = tmp_path / "chrome-profile"

        async def _test():
            browser = ChromeBrowser(user_data_dir=str(profile_dir))

            mock_context = MagicMock()
            mock_context.pages = []
            mock_context.new_page = AsyncMock(return_value=MagicMock())
            mock_chromium = MagicMock()
            mock_chromium.launch = AsyncMock()
            mock_chromium.launch_persistent_context = AsyncMock(return_value=mock_context)
            mock_pw = MagicMock()
            mock_pw.chromium = mock_chromium
            mock_pw.stop = AsyncMock()
            mock_async_pw = MagicMock()
            mock_async_pw.start = AsyncMock(return_value=mock_pw)

            with patch("playwright.async_api.async_playwright", return_value=mock_async_pw):
                await browser.spawn()

            mock_chromium.launch_persistent_context.assert_called_once()
            call = mock_chromium.launch_persistent_context.call_args
            assert call.args[0] == str(profile_dir)
            mock_chromium.launch.assert_not_called()
            assert profile_dir.is_dir()

        asyncio.run(_test())
