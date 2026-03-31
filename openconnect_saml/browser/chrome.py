"""Chrome/Chromium browser backend using Playwright.

Provides the same authentication interface as the Qt browser but uses
Playwright to drive Chrome/Chromium. Supports headless operation (no display
required) and auto-fill for username/password/TOTP fields.

Install with: pip install openconnect-saml[chrome]
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from openconnect_saml.config import Credentials

logger = structlog.get_logger()

# Default auto-fill selectors matching the Qt browser's behavior
_USERNAME_SELECTORS = [
    "input[type=email]",
    "input[name=loginfmt]",
    "input[name=login]",
    "input[name=username]",
    "input[name=user]",
]

_PASSWORD_SELECTORS = [
    "input[name=passwd]",
    "input[type=password]",
]

_TOTP_SELECTORS = [
    "input[id=idTxtBx_SAOTCC_OTC]",
    "input[name=otc]",
    "input[name=totp]",
]

_SUBMIT_SELECTORS = [
    "input[data-report-event=Signin_Submit]",
    "input[id=idSIButton9]",
    "input[type=submit]",
    "button[type=submit]",
]

_CLICK_SELECTORS = [
    "div[data-value=PhoneAppOTP]",
    "a[id=signInAnotherWay]",
    "input[id=KmsiCheckboxField]",
]


class ChromeBrowser:
    """Playwright-based Chrome/Chromium browser for SAML authentication.

    Parameters
    ----------
    headless : bool
        Run in headless mode (no visible window).
    proxy : str or None
        HTTP(S) proxy URL.
    timeout : int
        Navigation timeout in milliseconds.
    """

    def __init__(self, headless: bool = True, proxy: str | None = None, timeout: int = 60_000):
        self.headless = headless
        self.proxy = proxy
        self.timeout = timeout
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self.cookies: dict[str, str] = {}
        self.url: str | None = None

    async def spawn(self):
        """Launch the browser."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ImportError(
                "Playwright is not installed. Install with: pip install openconnect-saml[chrome]\n"
                "Then run: playwright install chromium"
            ) from exc

        self._playwright = await async_playwright().start()

        launch_args = {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}

        self._browser = await self._playwright.chromium.launch(**launch_args)
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout)

    async def authenticate_at(
        self,
        url: str,
        credentials: Credentials | None = None,
        final_url: str | None = None,
        token_cookie_name: str | None = None,
    ) -> dict[str, str]:
        """Navigate to the login URL and auto-fill credentials.

        Parameters
        ----------
        url : str
            The SAML login URL.
        credentials : Credentials or None
            Username/password/TOTP credentials for auto-fill.
        final_url : str or None
            The URL that indicates authentication is complete.
        token_cookie_name : str or None
            The cookie name containing the SSO token.

        Returns
        -------
        dict[str, str]
            Cookies from the browser context after authentication.
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call spawn() first.")

        logger.info("Chrome: navigating to login URL", url=url)
        await self._page.goto(url, wait_until="domcontentloaded")

        max_steps = 30
        for step in range(max_steps):
            current_url = self._page.url
            logger.debug("Chrome: auth step", step=step, url=current_url)

            # Check if we reached the final URL
            if final_url and self._url_matches(current_url, final_url):
                logger.info("Chrome: reached final URL")
                break

            # Check cookies for token
            if token_cookie_name:
                cookies = await self._context.cookies()
                for cookie in cookies:
                    if cookie["name"] == token_cookie_name:
                        logger.info("Chrome: found SSO token cookie")
                        self.cookies = {c["name"]: c["value"] for c in cookies}
                        self.url = current_url
                        return self.cookies

            # Auto-fill credentials
            if credentials:
                await self._auto_fill(credentials)

            # Wait for navigation or page change
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=5000)
                # Small delay for JavaScript to update the DOM
                await asyncio.sleep(1)
            except Exception:  # nosec
                pass

            # Check if URL changed (navigation happened)
            new_url = self._page.url
            if new_url == current_url:
                # No navigation — try clicking submit buttons
                await self._try_click_selectors(_CLICK_SELECTORS + _SUBMIT_SELECTORS)
                import contextlib

                with contextlib.suppress(Exception):
                    await self._page.wait_for_url(
                        lambda u: u != current_url,  # noqa: B023
                        timeout=5000,
                    )

        # Collect all cookies
        cookies = await self._context.cookies()
        self.cookies = {c["name"]: c["value"] for c in cookies}
        self.url = self._page.url
        return self.cookies

    async def _auto_fill(self, credentials: Credentials):
        """Auto-fill form fields with credentials."""
        # Fill username
        if credentials.username:
            for sel in _USERNAME_SELECTORS:
                try:
                    el = self._page.locator(sel).first
                    if await el.is_visible(timeout=500):
                        current_val = await el.input_value()
                        if not current_val:
                            await el.fill(credentials.username)
                            logger.debug("Chrome: filled username", selector=sel)
                            break
                except Exception:  # nosec
                    continue

        # Fill password
        if credentials.password:
            for sel in _PASSWORD_SELECTORS:
                try:
                    el = self._page.locator(sel).first
                    if await el.is_visible(timeout=500):
                        current_val = await el.input_value()
                        if not current_val:
                            await el.fill(credentials.password)
                            logger.debug("Chrome: filled password", selector=sel)
                            break
                except Exception:  # nosec
                    continue

        # Fill TOTP
        if credentials.totp:
            for sel in _TOTP_SELECTORS:
                try:
                    el = self._page.locator(sel).first
                    if await el.is_visible(timeout=500):
                        current_val = await el.input_value()
                        if not current_val:
                            await el.fill(credentials.totp)
                            logger.debug("Chrome: filled TOTP", selector=sel)
                            break
                except Exception:  # nosec
                    continue

    async def _try_click_selectors(self, selectors: list[str]):
        """Try to click elements matching the given selectors."""
        for sel in selectors:
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=300):
                    await el.click()
                    logger.debug("Chrome: clicked element", selector=sel)
                    return True
            except Exception:  # nosec
                continue
        return False

    @staticmethod
    def _url_matches(current: str, target: str) -> bool:
        """Check if current URL matches the target (ignoring query params)."""
        from urllib.parse import urlparse

        c = urlparse(current)
        t = urlparse(target)
        return c.scheme == t.scheme and c.netloc == t.netloc and c.path == t.path

    async def close(self):
        """Close the browser and clean up."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    async def __aenter__(self):
        await self.spawn()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
