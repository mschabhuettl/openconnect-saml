"""Chrome/Chromium browser backend using Playwright.

Provides the same authentication interface as the Qt browser but uses
Playwright to drive Chrome/Chromium. Supports headless operation (no display
required) and auto-fill for username/password/TOTP fields.

Install with: pip install openconnect-saml[chrome]
"""

from __future__ import annotations

import asyncio
import os
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
    "input[id=username]",
    "input[id=Username]",
    "input[id=userInput]",
    "input[autocomplete=username]",
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

_MFA_CHALLENGE_SELECTORS = [
    "text=/number matching/i",
    "text=/enter the number/i",
    "text=/approve sign in request/i",
    "text=/check your.*app/i",
]

# Subset of _CLICK_SELECTORS that switches the MFA method to "use a
# verification code". Only wanted when a TOTP source can actually fill
# that code — with push MFA they pull the flow off the approval screen.
_TOTP_SWITCH_SELECTORS = [
    "div[data-value=PhoneAppOTP]",
    "a[id=signInAnotherWay]",
]

# "Don't ask again for N days" MFA-remember checkboxes (verification-code
# and push screen variants). Only effective across sessions when a
# persistent profile (``user_data_dir``) is used.
_MFA_REMEMBER_SELECTORS = [
    "input[id=idChkBx_SAOTCC_TD]",
    "input[id=idChkBx_SAOTCAS_TD]",
    "input[name=DontShowAgain]",
]

# "Stay signed in?" (KMSI) page — nothing to fill, but it still needs a
# submit click to proceed. Detected explicitly so submit is never
# blind-clicked on pages we don't recognize.
_KMSI_SELECTORS = [
    "input[id=KmsiCheckboxField]",
    "text=/stay signed in/i",
]

# Visible error banner (e.g. wrong password). Blocks auto-resubmit so a
# bad credential is only ever sent once — never in a lockout loop.
_ERROR_SELECTORS = [
    "div[id=passwordError]",
    "div[id=usernameError]",
    "div[role=alert]",
]


def _helper_click_selectors(credentials) -> list[str]:
    """Session helper-choice selectors, adjusted to the credential setup.

    The MFA-method-switch selectors (``PhoneAppOTP`` / ``signInAnotherWay``)
    are only useful when a TOTP source is available to fill the code they
    lead to. With push MFA (no TOTP source) clicking them pulls the flow off
    the "approve the sign-in on your phone" screen onto a verification-code
    prompt nobody will fill — so they are dropped (#17).
    """
    totp_source = getattr(credentials, "totp_source", "none") if credentials else "none"
    if totp_source == "none":
        has_totp = False
    elif totp_source == "local":
        # Side-effect-free: reads the in-memory secret or the keyring.
        try:
            has_totp = bool(credentials.totp)
        except Exception:  # nosec
            has_totp = False
    else:
        # Provider-backed sources (1password, bitwarden, 2fauth, pass,
        # keepassxc, prompt) can produce a code at fill time.
        has_totp = True
    selectors = [s for s in _CLICK_SELECTORS if has_totp or s not in _TOTP_SWITCH_SELECTORS]
    return selectors + _MFA_REMEMBER_SELECTORS


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
        Directory for a persistent browser profile (Playwright
        ``launch_persistent_context``). When set, the IdP session and
        MFA-remember ("don't ask again for N days") cookies survive
        between connects, so repeat logins can skip password/MFA
        entirely. When ``None`` (default), the context is ephemeral and
        nothing is written to disk — the previous behavior.
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

        if self.executable_path:
            # Fail early with an actionable message rather than letting
            # Playwright raise its denser "Executable doesn't exist" later.
            from pathlib import Path

            if not Path(self.executable_path).is_file():
                raise RuntimeError(
                    f"--chrome-executable path does not exist: {self.executable_path}\n"
                    "Point it at an installed Chromium/Chrome/Edge binary, "
                    "e.g. /usr/bin/chromium or /usr/bin/google-chrome-stable."
                )

        self._playwright = await async_playwright().start()

        launch_args = {
            "headless": self.headless,
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

        user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        try:
            if self.user_data_dir:
                # Persistent profile: keeps the IdP session and MFA-remember
                # cookies between connects. 0o700 — the profile stores live
                # session cookies.
                profile_dir = os.path.expanduser(self.user_data_dir)
                os.makedirs(profile_dir, mode=0o700, exist_ok=True)
                self._context = await self._playwright.chromium.launch_persistent_context(
                    profile_dir, user_agent=user_agent, **launch_args
                )
            else:
                self._browser = await self._playwright.chromium.launch(**launch_args)
        except Exception as exc:
            # ``async_playwright().start()`` already spawned the driver
            # process. If launch raises, ``__aexit__`` will never run
            # (because ``__aenter__`` aborted), so stop the driver here
            # to avoid leaking node subprocesses + sockets. Swallow
            # cleanup errors — they shouldn't mask the real failure.
            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass
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
        if self._context is None:
            self._context = await self._browser.new_context(user_agent=user_agent)
        # launch_persistent_context opens with an initial blank page.
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
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
        clicked_selectors: set[str] = set()
        helper_selectors = _helper_click_selectors(credentials)
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
                # No navigation — click helper choices once per session, and
                # submit whenever there is unsubmitted data. ``filled_any``
                # alone is not enough: Microsoft's login SPA keeps the same
                # URL across the email → password → KMSI steps and
                # pre-renders the password input while the email screen is
                # still shown, so the fill can land one step before the
                # screen that needs its submit click (the session-wide
                # click dedupe would then never submit that screen).
                await self._try_click_selectors(helper_selectors, clicked_selectors)
                if filled_any or await self._has_pending_secret() or await self._is_kmsi_page():
                    await self._try_click_selectors(_SUBMIT_SELECTORS, set())
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

    async def _auto_fill(self, credentials: Credentials) -> bool:
        """Auto-fill form fields with credentials. Returns True if a field changed."""
        filled_any = False
        # Fill username
        if credentials.username:
            for sel in _USERNAME_SELECTORS:
                try:
                    el = self._page.locator(sel).first
                    if await el.is_visible(timeout=500):
                        current_val = await el.input_value()
                        if not current_val:
                            await el.fill(credentials.username)
                            filled_any = True
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
                            filled_any = True
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
                            filled_any = True
                            logger.debug("Chrome: filled TOTP", selector=sel)
                            break
                except Exception:  # nosec
                    continue
        return filled_any

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

    async def _has_pending_secret(self) -> bool:
        """A visible password/TOTP field already holds a value.

        Microsoft's SPA pre-renders the password input while the email
        screen is still displayed, so ``_auto_fill`` can fill it one step
        before its screen is shown — ``filled_any`` is then False on the
        step where the password screen actually needs its submit click.
        Never returns True while an error banner is visible, so a wrong
        credential is not re-submitted in a loop.
        """
        for sel in _ERROR_SELECTORS:
            try:
                if await self._page.locator(sel).first.is_visible(timeout=100):
                    return False
            except Exception:  # nosec
                continue
        for sel in _PASSWORD_SELECTORS + _TOTP_SELECTORS:
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=200) and await el.input_value():
                    return True
            except Exception:  # nosec
                continue
        return False

    async def _is_kmsi_page(self) -> bool:
        """Detect the "Stay signed in?" (KMSI) page so it can be submitted."""
        for sel in _KMSI_SELECTORS:
            try:
                if await self._page.locator(sel).first.is_visible(timeout=200):
                    return True
            except Exception:  # nosec
                continue
        return False

    async def _try_click_selectors(self, selectors: list[str], clicked: set[str] | None = None):
        """Try to click elements matching the given selectors.

        Checkboxes that are already checked are skipped instead of clicked,
        so a helper checkbox (KMSI / MFA-remember) is never toggled back off.
        """
        clicked = clicked if clicked is not None else set()
        for sel in selectors:
            if sel in clicked:
                continue
            try:
                el = self._page.locator(sel).first
                if await el.is_visible(timeout=300):
                    try:
                        el_type = (await el.get_attribute("type") or "").lower()
                        if el_type == "checkbox" and await el.is_checked():
                            clicked.add(sel)
                            continue
                    except Exception:  # nosec
                        pass
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
        if self._context and not self._browser:
            # launch_persistent_context has no separate Browser object —
            # closing the context shuts Chromium down and flushes the
            # persistent profile to disk.
            await self._context.close()
        self._context = None
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
