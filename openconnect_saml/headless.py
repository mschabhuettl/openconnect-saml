"""Headless SAML authenticator — no browser/display required.

Provides two strategies:
1. **Automatic**: Uses requests + lxml to submit SAML forms (username/password/TOTP)
   automatically. Works for standard Azure AD / Microsoft Online flows.
2. **Callback**: Starts a local HTTP server and prints the SAML URL for the user
   to open in their own browser. The server captures the auth callback.

Falls back from automatic → callback when the flow can't be automated
(e.g. CAPTCHA, unsupported MFA, JavaScript-heavy pages).
"""

from __future__ import annotations

import asyncio
import html
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urljoin, urlparse

import requests
import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

# Default port for the local callback server
DEFAULT_CALLBACK_PORT = 29786
# Timeout for waiting on callback (seconds)
DEFAULT_CALLBACK_TIMEOUT = 300


class HeadlessAuthError(Exception):
    """Raised when headless authentication fails."""


class HeadlessAuthenticator:
    """Authenticate to a SAML SSO endpoint without a browser.

    Parameters
    ----------
    proxy : str or None
        HTTP(S) proxy URL.
    credentials : Credentials or None
        Username/password/TOTP credentials.
    ssl_legacy : bool
        Enable legacy SSL renegotiation.
    timeout : int
        HTTP request timeout in seconds.
    callback_port : int
        Port for the local callback server.
    callback_timeout : int
        Max seconds to wait for browser callback.
    """

    def __init__(
        self,
        proxy=None,
        credentials=None,
        ssl_legacy=False,
        timeout=30,
        callback_port=DEFAULT_CALLBACK_PORT,
        callback_timeout=DEFAULT_CALLBACK_TIMEOUT,
    ):
        self.proxy = proxy
        self.credentials = credentials
        self.ssl_legacy = ssl_legacy
        self.timeout = timeout
        self.callback_port = callback_port
        self.callback_timeout = callback_timeout
        self.session = self._create_session()

    def _create_session(self):
        """Create a requests session with appropriate headers."""
        from openconnect_saml.authenticator import SSLLegacyAdapter

        session = requests.Session()
        if self.proxy:
            session.proxies = {"http": self.proxy, "https": self.proxy}
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
        )
        if self.ssl_legacy:
            from openconnect_saml.authenticator import SSLLegacyAdapter

            adapter = SSLLegacyAdapter()
            session.mount("https://", adapter)
        return session

    async def authenticate(self, auth_request_response):
        """Attempt headless authentication and return the SSO token.

        First tries automatic form-based auth. If that fails,
        falls back to the callback server approach.
        """
        login_url = str(auth_request_response.login_url)
        login_final_url = str(auth_request_response.login_final_url)
        token_cookie_name = str(auth_request_response.token_cookie_name)

        if self.credentials and self.credentials.username:
            logger.info("Attempting automatic headless authentication")
            try:
                token = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._auto_authenticate,
                    login_url,
                    login_final_url,
                    token_cookie_name,
                )
                if token:
                    return token
            except HeadlessAuthError as exc:
                logger.warning(
                    "Automatic headless auth failed, falling back to callback server",
                    error=str(exc),
                )
            except Exception as exc:
                logger.warning(
                    "Automatic headless auth failed unexpectedly, falling back to callback server",
                    error=str(exc),
                )

        # Fallback: callback server
        logger.info("Starting callback server for browser-based authentication")
        token = await asyncio.get_event_loop().run_in_executor(
            None,
            self._callback_authenticate,
            login_url,
            login_final_url,
            token_cookie_name,
        )
        return token

    def _auto_authenticate(self, login_url, login_final_url, token_cookie_name):
        """Automatic form-based authentication using requests + lxml."""
        from lxml import html as lxml_html

        resp = self.session.get(login_url, timeout=self.timeout, allow_redirects=True)
        resp.raise_for_status()

        max_steps = 20
        for step in range(max_steps):
            current_url = resp.url
            logger.debug("Headless auth step", step=step, url=current_url)

            # Check if we've reached the final URL
            if self._url_matches(current_url, login_final_url):
                token = self._extract_token(resp, token_cookie_name)
                if token:
                    logger.info("Headless authentication successful")
                    return token

            # Check for token in cookies
            token = self._check_cookies_for_token(token_cookie_name)
            if token:
                logger.info("Headless authentication successful (cookie)")
                return token

            # Parse the page
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type.lower() and "xml" not in content_type.lower():
                raise HeadlessAuthError(f"Unexpected content type: {content_type}")

            doc = lxml_html.fromstring(resp.content, base_url=current_url)

            # Find forms
            forms = doc.forms
            if not forms:
                # Maybe a JavaScript redirect — check for meta refresh or common patterns
                meta_url = self._find_meta_refresh(doc, current_url)
                if meta_url:
                    resp = self.session.get(meta_url, timeout=self.timeout, allow_redirects=True)
                    resp.raise_for_status()
                    continue

                # Check for auto-submit forms via regex as fallback
                auto_url = self._find_auto_post_form(resp.text, current_url)
                if auto_url:
                    resp = self.session.post(
                        auto_url[0],
                        data=auto_url[1],
                        timeout=self.timeout,
                        allow_redirects=True,
                    )
                    resp.raise_for_status()
                    continue

                raise HeadlessAuthError("No forms found on page and no redirect detected")

            # Process the first relevant form
            form = forms[0]
            action = form.action or current_url
            if not action.startswith("http"):
                action = urljoin(current_url, action)

            method = (form.method or "POST").upper()

            # Collect form fields
            form_data = {}
            fields = form.fields
            for name in fields:
                form_data[name] = fields[name] or ""

            # Fill in credentials
            filled = self._fill_form(form, form_data, doc)

            if not filled:
                # Check if this is a SAML response form (auto-submit)
                if "SAMLResponse" in form_data or "SAMLRequest" in form_data:
                    logger.debug("Auto-submitting SAML form")
                else:
                    logger.debug("No credential fields found to fill, submitting as-is")

            logger.debug(
                "Submitting form", action=action, method=method, fields=list(form_data.keys())
            )

            if method == "GET":
                resp = self.session.get(
                    action, params=form_data, timeout=self.timeout, allow_redirects=True
                )
            else:
                resp = self.session.post(
                    action, data=form_data, timeout=self.timeout, allow_redirects=True
                )
            resp.raise_for_status()

        raise HeadlessAuthError("Max authentication steps exceeded")

    def _fill_form(self, form, form_data, doc):
        """Fill form fields with credentials. Returns True if anything was filled."""
        if not self.credentials:
            return False

        filled = False
        username = self.credentials.username
        password = self.credentials.password
        totp = self.credentials.totp

        # Strategy: look at input types and common field names
        for name, _value in list(form_data.items()):
            input_el = form.xpath(f'.//input[@name="{name}"]')
            if not input_el:
                continue
            el = input_el[0]
            input_type = (el.get("type") or "text").lower()
            name_lower = name.lower()

            # Username / email fields
            if input_type in ("email", "text") and self._is_username_field(name_lower, el):
                if username:
                    form_data[name] = username
                    filled = True
                    logger.debug("Filled username field", field=name)

            # Password fields
            elif input_type == "password":
                if password:
                    form_data[name] = password
                    filled = True
                    logger.debug("Filled password field", field=name)

            # TOTP fields
            elif self._is_totp_field(name_lower, el) and totp:
                form_data[name] = totp
                filled = True
                logger.debug("Filled TOTP field", field=name)

        return filled

    @staticmethod
    def _is_username_field(name_lower, el):
        """Heuristic to detect username/email input fields."""
        username_hints = ("user", "email", "login", "loginfmt", "username", "account")
        if any(h in name_lower for h in username_hints):
            return True
        placeholder = (el.get("placeholder") or "").lower()
        if any(h in placeholder for h in username_hints):
            return True
        autocomplete = (el.get("autocomplete") or "").lower()
        return autocomplete in ("username", "email")

    @staticmethod
    def _is_totp_field(name_lower, el):
        """Heuristic to detect TOTP/OTC input fields."""
        totp_hints = ("otp", "otc", "totp", "verification", "code", "token", "mfa")
        if any(h in name_lower for h in totp_hints):
            return True
        placeholder = (el.get("placeholder") or "").lower()
        return any(h in placeholder for h in totp_hints)

    @staticmethod
    def _find_meta_refresh(doc, base_url):
        """Find meta http-equiv=refresh redirect URLs."""
        metas = doc.xpath('//meta[@http-equiv="refresh" or @http-equiv="Refresh"]')
        for meta in metas:
            content = meta.get("content", "")
            match = re.search(r"url\s*=\s*['\"]?([^'\";\s]+)", content, re.IGNORECASE)
            if match:
                url = match.group(1)
                if not url.startswith("http"):
                    url = urljoin(base_url, url)
                return url
        return None

    @staticmethod
    def _find_auto_post_form(html_text, base_url):
        """Detect JavaScript auto-submit forms (common in SAML flows)."""
        # Pattern: form with action + hidden inputs + document.forms[0].submit()
        form_match = re.search(
            r'<form[^>]*action\s*=\s*["\']([^"\']+)["\'][^>]*>(.*?)</form>',
            html_text,
            re.DOTALL | re.IGNORECASE,
        )
        if not form_match:
            return None

        if "submit()" not in html_text.lower():
            return None

        action = html.unescape(form_match.group(1))
        if not action.startswith("http"):
            action = urljoin(base_url, action)

        body = form_match.group(2)
        data = {}
        for inp in re.finditer(
            r'<input[^>]*name\s*=\s*["\']([^"\']+)["\'][^>]*value\s*=\s*["\']([^"\']*)["\']',
            body,
            re.IGNORECASE,
        ):
            data[html.unescape(inp.group(1))] = html.unescape(inp.group(2))
        # Also catch reversed order (value before name)
        for inp in re.finditer(
            r'<input[^>]*value\s*=\s*["\']([^"\']*)["\'][^>]*name\s*=\s*["\']([^"\']+)["\']',
            body,
            re.IGNORECASE,
        ):
            key = html.unescape(inp.group(2))
            if key not in data:
                data[key] = html.unescape(inp.group(1))

        return (action, data)

    def _url_matches(self, current, target):
        """Check if current URL matches the target (ignoring query params)."""
        c = urlparse(current)
        t = urlparse(target)
        return c.scheme == t.scheme and c.netloc == t.netloc and c.path == t.path

    def _extract_token(self, resp, token_cookie_name):
        """Try to extract the SSO token from response cookies or session cookies."""
        # Check response cookies
        if token_cookie_name in resp.cookies:
            return resp.cookies[token_cookie_name]
        return self._check_cookies_for_token(token_cookie_name)

    def _check_cookies_for_token(self, token_cookie_name):
        """Check session cookies for the SSO token."""
        for cookie in self.session.cookies:
            if cookie.name == token_cookie_name:
                return cookie.value
        return None

    def _callback_authenticate(self, login_url, login_final_url, token_cookie_name):
        """Start a local HTTP server and wait for the user to authenticate in their browser."""
        result = {"token": None, "error": None}
        server_ready = threading.Event()
        server = None

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                """Handle GET callback with token in query params or cookies."""
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)

                # Try to get token from query params
                token = None
                if token_cookie_name in params:
                    token = params[token_cookie_name][0]

                # Check common parameter names
                for key in ("token", "session_token", "sso_token", "code"):
                    if key in params and not token:
                        token = params[key][0]

                if token:
                    result["token"] = token
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h1>Authentication successful!</h1>"
                        b"<p>You can close this window and return to the terminal.</p>"
                        b"</body></html>"
                    )
                else:
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(
                        b"<html><body><h1>Missing token</h1>"
                        b"<p>Authentication callback received but no token found.</p>"
                        b"</body></html>"
                    )

            def do_POST(self):
                """Handle POST callback (some SAML flows POST the response)."""
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8", errors="replace")
                params = parse_qs(body)

                token = None
                if token_cookie_name in params:
                    token = params[token_cookie_name][0]

                for key in ("token", "session_token", "sso_token", "SAMLResponse"):
                    if key in params and not token:
                        token = params[key][0]

                if token:
                    result["token"] = token

                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h1>Authentication callback received.</h1>"
                    b"<p>You can close this window.</p></body></html>"
                )

            def log_message(self, format, *args):
                """Suppress default HTTP server logging."""
                logger.debug("Callback server", message=format % args)

        try:
            server = HTTPServer(("127.0.0.1", self.callback_port), CallbackHandler)
        except OSError:
            # Port in use — try random port
            server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
            self.callback_port = server.server_address[1]

        server_ready.set()
        callback_url = f"http://127.0.0.1:{self.callback_port}/callback"

        # Print the URL for the user
        separator = "=" * 70
        print(f"\n{separator}")
        print("HEADLESS AUTHENTICATION — Browser Required")
        print(separator)
        print("\n  Open this URL in your browser:\n")
        print(f"  {login_url}")
        print("\n  After authenticating, you will be redirected.")
        print("  If prompted for a callback URL, use:\n")
        print(f"  {callback_url}")
        print(f"\n  Waiting for authentication (timeout: {self.callback_timeout}s)...")
        print(f"{separator}\n")

        # Run server with timeout
        server.timeout = 1  # Check every second
        deadline = time.monotonic() + self.callback_timeout

        try:
            while time.monotonic() < deadline and result["token"] is None:
                server.handle_request()
        finally:
            server.server_close()

        if result["token"]:
            logger.info("Authentication received via callback server")
            return result["token"]

        raise HeadlessAuthError(
            f"Callback server timed out after {self.callback_timeout}s. "
            "No authentication response received."
        )
