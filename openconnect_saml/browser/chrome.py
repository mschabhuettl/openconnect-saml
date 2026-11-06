"""Chrome/Chromium browser backend using Playwright.

Provides the same authentication interface as the Qt browser but uses
Playwright to drive Chrome/Chromium. Supports headless operation (no display
required) and auto-fill for username/password/TOTP fields.

Install with: pip install openconnect-saml[chrome]
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from openconnect_saml.browser import Terminated

if TYPE_CHECKING:
    from openconnect_saml.config import Credentials

logger = structlog.get_logger()

# Default auto-fill selectors matching the Qt browser's behavior
_USERNAME_SELECTORS = [
    "input[type=email]",
    "input[name=loginfmt]",
    "input[name=login]",
    "input[name=j_username]",
    "input[id=j_username]",
    "input[name=username]",
    "input[name=user]",
    "input[id=username]",
    "input[id=Username]",
    "input[id=userInput]",
    "input[autocomplete=username]",
]
_USERNAME_LABEL = re.compile(r"user\s*name|netid|login\s*id|e-?mail", re.IGNORECASE)

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

_MFA_CHALLENGE_SELECTORS = [
    "text=/number matching/i",
    "text=/enter the number/i",
    "text=/approve sign in request/i",
    "text=/check your.*app/i",
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
    channel : str or None
        Playwright browser channel — when set, Playwright uses a
        system-installed Chrome/Edge instead of its bundled Chromium
        download. Valid values: ``chrome``, ``chrome-beta``,
        ``chrome-dev``, ``chrome-canary``, ``msedge``, ``msedge-beta``,
        ``msedge-dev``, ``msedge-canary``. When ``None`` (default),
        Playwright uses its bundled Chromium (the ~150 MB download
        installed via ``playwright install chromium``).
    executable_path : str or None
        Absolute path to a Chromium/Chrome/Edge binary to drive directly
        (Playwright ``executable_path=``). Lets users with a system
        ``chromium`` (e.g. ``/usr/bin/chromium``) skip both the bundled
        Chromium download and the channel mechanism — ``channel`` has no
        ``chromium`` value, so a plain distro ``chromium`` can only be
        reached this way (#39, #24). Takes precedence over ``channel``
        when both are given.
    user_data_dir : str or None
        Dedicated persistent profile directory. Retains cookies, storage,
        and installed extensions. Do not use your everyday browser profile.
    """

    def __init__(
        self,
        headless: bool = True,
        proxy: str | None = None,
        timeout: int = 60_000,
        channel: str | None = None,
        executable_path: str | None = None,
        user_data_dir: str | None = None,
    ):
        self.headless = headless
        self.proxy = proxy
        self.timeout = timeout
        self.channel = channel
        self.executable_path = executable_path
        self.user_data_dir = user_data_dir
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._login_pages = []
        self.cookies: dict[str, str] = {}
        self.url: str | None = None

    async def spawn(self):
        """Launch the browser."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ImportError(
                "Playwright is not installed. Install it via:\n"
                "  • pip:  pip install 'openconnect-saml[chrome]'\n"
                "  • AUR:  yay -S python-playwright   "
                "(NOT 'aur/playwright' — that's the Node.js library "
                "and won't satisfy `import playwright`)\n"
                "Then run: playwright install chromium"
            ) from exc

        if self.executable_path and not Path(self.executable_path).is_file():
            raise RuntimeError(
                f"--chrome-executable path does not exist: {self.executable_path}\n"
                "Point it at an installed Chromium/Chrome/Edge binary, "
                "e.g. /usr/bin/chromium or /usr/bin/google-chrome-stable."
            )

        self._playwright = await async_playwright().start()

        launch_args = {
            "headless": self.headless,
            "chromium_sandbox": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if self.proxy:
            launch_args["proxy"] = {"server": self.proxy}
        if self.executable_path:
            # Drive a specific binary directly. This is the only way to use
            # a plain distro ``chromium`` (Playwright has no ``chromium``
            # channel) without the ~150 MB bundled-Chromium download (#39).
            # ``executable_path`` and ``channel`` are mutually exclusive in
            # Playwright, so an explicit executable wins and channel is
            # ignored (with a warning if the user set both).
            launch_args["executable_path"] = self.executable_path
            if self.channel:
                logger.warning(
                    "Both --chrome-executable and --chrome-channel set; "
                    "using the executable and ignoring the channel.",
                    executable_path=self.executable_path,
                    channel=self.channel,
                )
        elif self.channel:
            # Use a system-installed Chrome / Edge instead of the
            # Playwright-bundled Chromium. Saves the ~150 MB download
            # if the user already has Chrome/Edge installed locally.
            launch_args["channel"] = self.channel

        try:
            if self.user_data_dir:
                profile = Path(self.user_data_dir).expanduser().resolve()
                profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Playwright disables extensions by default, even when they
                # were installed interactively in a persistent profile.
                self._context = await self._playwright.chromium.launch_persistent_context(
                    str(profile),
                    ignore_default_args=[
                        "--disable-extensions",
                        "--use-mock-keychain",
                        "--password-store=basic",
                    ],
                    **launch_args,
                )
            else:
                self._browser = await self._playwright.chromium.launch(**launch_args)
                self._context = await self._browser.new_context()
            self._page = (
                self._context.pages[0]
                if self.user_data_dir and self._context.pages
                else await self._context.new_page()
            )
            self._page.set_default_timeout(self.timeout)
        except Exception as exc:
            # ``async_playwright().start()`` already spawned the driver
            # process. If launch raises, ``__aexit__`` will never run
            # (because ``__aenter__`` aborted), so stop the driver here
            # to avoid leaking node subprocesses + sockets. Swallow
            # cleanup errors — they shouldn't mask the real failure.
            with contextlib.suppress(Exception):
                await self.close()
            self._playwright = None
            # Most common cause: ``pip install ...[chrome]`` ran but
            # ``playwright install chromium`` didn't, so the Chromium
            # binary is missing. Playwright's own message is dense, so
            # we wrap it with the actionable next step.
            msg = str(exc).lower()
            if "executable" in msg or "browsertype" in msg or "doesn't exist" in msg:
                raise RuntimeError(
                    "Chromium isn't available to Playwright. Either:\n"
                    "  • run `playwright install chromium` (one-off; downloads the "
                    "~150 MB bundle into your virtualenv), or\n"
                    "  • point at an already-installed browser with "
                    "`--chrome-executable /path/to/chromium` (e.g. /usr/bin/chromium), or\n"
                    "  • use `--chrome-channel chrome|msedge` if you have Google "
                    "Chrome / Microsoft Edge installed."
                ) from exc
            raise

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

        logger.info("Opening Chrome for SSO")
        # Track only popups opened by the login page, not unrelated tabs in
        # a persistent profile. IdP popups can open further login windows.
        self._login_pages = [self._page]
        self._page.on("popup", self._track_login_popup)
        cookie_url = final_url or url
        if token_cookie_name:
            # SSO completion cookies belong to a single handshake. A saved
            # copy must not be mistaken for the result of the new login.
            for cookie in await self._context.cookies(cookie_url):
                if cookie["name"] == token_cookie_name:
                    await self._context.clear_cookies(
                        name=token_cookie_name, domain=cookie["domain"], path=cookie["path"]
                    )
        await self._page.goto(url, wait_until="domcontentloaded")

        max_steps = 30
        clicked_selectors: set[str] = set()
        for step in range(max_steps):
            # A successful login can be followed by the user closing the
            # window before the next poll. Read its result before treating
            # closed pages as cancellation.
            if token_cookie_name:
                try:
                    cookies = await self._context.cookies(cookie_url)
                except Exception:
                    if all(page.is_closed() for page in self._login_pages):
                        raise Terminated() from None
                    raise
                for cookie in cookies:
                    if cookie["name"] == token_cookie_name:
                        logger.info("Chrome: found SSO token cookie")
                        self.cookies = {c["name"]: c["value"] for c in cookies}
                        self.url = self._page.url
                        return self.cookies

            live_pages = [page for page in self._login_pages if not page.is_closed()]
            if not live_pages:
                raise Terminated()
            self._page = live_pages[-1]
            current_url = self._page.url
            logger.debug("Chrome: auth step", step=step)

            if not token_cookie_name and final_url and self._url_matches(current_url, final_url):
                logger.info("Chrome: reached final URL")
                break

            # Auto-fill credentials and report MFA prompts without repeatedly refreshing the page.
            filled_any = False
            if credentials:
                filled_any = await self._auto_fill(credentials)
            await self._detect_mfa_challenge()

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
                # No navigation — click helper choices once, and only submit after filling data.
                selectors = (
                    []
                    if getattr(credentials, "username_only", False)
                    else _CLICK_SELECTORS + (_SUBMIT_SELECTORS if filled_any else [])
                )
                await self._try_click_selectors(selectors, clicked_selectors)
                with contextlib.suppress(Exception):
                    await self._page.wait_for_url(
                        lambda u: u != current_url,  # noqa: B023
                        timeout=5000,
                    )

        # Collect all cookies
        cookies = await self._context.cookies(cookie_url)
        self.cookies = {c["name"]: c["value"] for c in cookies}
        self.url = self._page.url
        return self.cookies

    def _track_login_popup(self, page):
        self._login_pages.append(page)
        page.on("popup", self._track_login_popup)

    async def _auto_fill(self, credentials: Credentials) -> bool:
        """Fill empty, visible fields, including forms embedded in login frames."""
        filled_any = False
        fields = [
            ("username", _USERNAME_SELECTORS, credentials.username),
            ("password", _PASSWORD_SELECTORS, credentials.password),
            ("TOTP", _TOTP_SELECTORS, credentials.totp),
        ]
        for frame in self._page.frames:
            username_found = False
            for label, selectors, value in fields:
                if not value:
                    continue
                for selector in selectors:
                    try:
                        element = frame.locator(f"{selector}:visible").first
                        if await element.is_visible():
                            if label == "username":
                                username_found = True
                            if not await element.input_value():
                                await element.fill(value)
                                filled_any = True
                                logger.debug("Chrome: filled field", field=label, selector=selector)
                            break
                    except Exception:  # nosec - frames can detach during SSO navigation
                        continue
            if credentials.username and not username_found:
                filled_any = (
                    await self._fill_labeled_username(frame, credentials.username) or filled_any
                )
        return filled_any

    async def _fill_labeled_username(self, frame, username):
        """Handle custom field names through the form's accessible label/placeholder."""
        for candidates in (
            frame.get_by_label(_USERNAME_LABEL),
            frame.get_by_placeholder(_USERNAME_LABEL),
        ):
            try:
                for element in await candidates.all():
                    if (
                        await element.get_attribute("type") in (None, "text", "email", "tel")
                        and await element.is_visible()
                        and not await element.input_value()
                    ):
                        await element.fill(username)
                        logger.debug("Chrome: filled username using field label")
                        return True
            except Exception:  # nosec - frames can detach during SSO navigation
                continue
        return False

    async def _detect_mfa_challenge(self):
        """Log a clear hint when the page is waiting for push/number MFA (#17)."""
        for sel in _MFA_CHALLENGE_SELECTORS:
            try:
                if await self._page.locator(sel).first.is_visible(timeout=200):
                    logger.info(
                        "Chrome: MFA challenge detected; approve it in your authenticator/security-key flow"
                    )
                    return True
            except Exception:  # nosec
                continue
        return False

    async def _try_click_selectors(self, selectors: list[str], clicked: set[str] | None = None):
        """Try to click elements matching the given selectors."""
        clicked = clicked if clicked is not None else set()
        for sel in selectors:
            if sel in clicked:
                continue
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=300):
                    await el.click()
                    clicked.add(sel)
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
        for page in self._login_pages:
            page.remove_listener("popup", self._track_login_popup)
        self._login_pages = []
        try:
            if self._context:
                await self._context.close()
        finally:
            try:
                if self._browser:
                    await self._browser.close()
            finally:
                if self._playwright:
                    await self._playwright.stop()
                self._browser = self._context = self._page = self._playwright = None

    async def __aenter__(self):
        await self.spawn()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
