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
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests
import structlog

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()

# Default port for the local callback server
DEFAULT_CALLBACK_PORT = 29786
# Timeout for waiting on callback (seconds)
DEFAULT_CALLBACK_TIMEOUT = 300


# Hosts that handle authentication for Microsoft Entra ID / Azure AD /
# Microsoft 365 SSO. The login flow is JavaScript-heavy (Conditional
# Access, FIDO2, push, hash-based redirects) and the pure ``requests``
# scripted path can't drive it reliably. Detect these hosts up-front so
# we can give a clearer error than "Max authentication steps exceeded".
_ENTRA_HOSTS = (
    "login.microsoftonline.com",
    "login.microsoftonline.us",
    "login.microsoftonline.de",
    "login.partner.microsoftonline.cn",
    "login.live.com",
    "login.windows.net",
)


def _is_ms_entra_idp(login_url: str) -> bool:
    try:
        host = (urlparse(login_url).hostname or "").lower()
    except (ValueError, AttributeError):
        return False
    return any(host == h or host.endswith("." + h) for h in _ENTRA_HOSTS)


_ENTRA_HEADLESS_HINT = (
    "Microsoft Entra ID / Azure AD detected as the IdP. The pure-HTTP "
    "headless backend can't drive its JavaScript-based login flow.\n"
    "Use ``--browser chrome`` instead — Playwright runs Chromium "
    "headless under the hood (no DISPLAY required, works on remote "
    "servers and inside containers).\n\n"
    "  pip install 'openconnect-saml[chrome]'\n"
    "  playwright install chromium\n"
    "  openconnect-saml connect <profile> --browser chrome\n"
)


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
        allowed_hosts: list[str] | None = None,
        verify_tls: bool = True,
        auth_script: str | None = None,
    ):
        self.proxy = proxy
        self.credentials = credentials
        self.ssl_legacy = ssl_legacy
        self.timeout = timeout
        self.callback_port = callback_port
        self.callback_timeout = callback_timeout
        # Hostname whitelist for headless redirect chain (#11). When None,
        # the gateway and login_url hosts are auto-allowed. When a non-empty
        # list, every redirect target must match (exact hostname or
        # ``*.suffix`` glob).
        self.allowed_hosts: list[str] | None = list(allowed_hosts) if allowed_hosts else None
        self.verify_tls = verify_tls
        self.auth_script = auth_script
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
        session.verify = self.verify_tls
        if not self.verify_tls:
            # ``REQUESTS_CA_BUNDLE`` env var would otherwise override
            # ``session.verify=False`` and silently re-enable verification.
            session.trust_env = False
        return session

    def _host_allowed(self, url: str) -> bool:
        """Check if ``url``'s hostname is on the whitelist.

        ``self.allowed_hosts == None`` means "no whitelist enforcement"
        (default behaviour). An empty list means "block everything"
        (probably never useful but explicit). Globs of the form
        ``*.example.com`` match any subdomain of ``example.com``.
        """
        if self.allowed_hosts is None:
            return True
        try:
            host = (urlparse(url).hostname or "").lower()
        except (ValueError, AttributeError):
            return False
        if not host:
            return False
        for entry in self.allowed_hosts:
            entry = entry.strip().lower()
            if not entry:
                continue
            if entry == host:
                return True
            if entry.startswith("*.") and host.endswith(entry[1:]):
                return True
        return False

    async def authenticate(self, auth_request_response):
        """Attempt headless authentication and return the SSO token.

        Strategy:
        1. If a script is provided, run that, otherwise...
        2. If we recognise the IdP as Microsoft Entra ID / Azure AD,
           run the ``_auto_authenticate_entra`` scripted flow. That
           speaks Microsoft's multi-step login protocol
           (GetCredentialType → password → MFA → KMSI → SAML form) and
           works for tenants that allow username + password + TOTP.
           Failure messages from this path are kept verbatim (they
           usually identify the cause: bad credentials, FIDO2-only
           tenant, federated tenant) and the ``--browser chrome``
           hint is appended as guidance.
        3. For non-Entra IdPs, run the generic ``_auto_authenticate``
           form scraper.
        4. If the scraper raises and we're on Entra, surface the same
           combined message — for non-Entra, fall through to the
           callback server (which prints a URL the user opens in a
           browser).
        """
        login_url = str(auth_request_response.login_url)
        login_final_url = str(auth_request_response.login_final_url)
        token_cookie_name = str(auth_request_response.token_cookie_name)

        is_entra = _is_ms_entra_idp(login_url)

        # Priority 1: External auth script
        if self.auth_script and self.credentials.username and self.credentials.password:
            logger.info("Using external auth script", script=self.auth_script)
            try:
                token = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self._run_auth_script,
                    login_url,
                    login_final_url,
                    token_cookie_name,
                )
                if token:
                    return token
            except HeadlessAuthError as exc:
                logger.warning(
                    "Auth script failed, falling back to callback server",
                    error=str(exc),
                )
            except Exception as exc:
                logger.warning(
                    "Auth script failed unexpectedly, falling back to callback server",
                    error=str(exc),
                )

        # Priority 2: Automatic form-based auth
        if self.credentials and self.credentials.username:
            if is_entra:
                logger.info("Attempting scripted Microsoft Entra ID login")
                try:
                    token = await asyncio.get_event_loop().run_in_executor(
                        None,
                        self._auto_authenticate_entra,
                        login_url,
                        login_final_url,
                        token_cookie_name,
                    )
                    if token:
                        return token
                except Exception as exc:
                    # Keep the actionable cause (wrong creds, FIDO2-only
                    # tenant, federated tenant, ...) and append the
                    # ``--browser chrome`` hint so users have both the
                    # diagnosis and the next step in one message.
                    raise HeadlessAuthError(f"{exc}\n\n{_ENTRA_HEADLESS_HINT}") from exc
            else:
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
                        "Automatic headless auth failed unexpectedly, "
                        "falling back to callback server",
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

        # Auto-extend the whitelist (if any) with the obvious endpoints
        # so the user doesn't have to list the gateway + IdP themselves.
        if self.allowed_hosts is not None:
            for url in (login_url, login_final_url):
                host = urlparse(url).hostname
                if host and host.lower() not in (h.lower() for h in self.allowed_hosts):
                    self.allowed_hosts.append(host)

        if not self._host_allowed(login_url):
            raise HeadlessAuthError(
                f"Login URL host {urlparse(login_url).hostname!r} not in allowed_hosts"
            )

        resp = self.session.get(login_url, timeout=self.timeout, allow_redirects=True)
        resp.raise_for_status()

        max_steps = 20
        for step in range(max_steps):
            current_url = resp.url
            logger.debug("Headless auth step", step=step, url=current_url)
            if not self._host_allowed(current_url):
                raise HeadlessAuthError(
                    f"Refusing to follow redirect to {urlparse(current_url).hostname!r} "
                    "(not in allowed_hosts whitelist)"
                )

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

    # -- Microsoft Entra ID / Azure AD / Microsoft 365 --------------------
    #
    # Microsoft's login UX is JS-driven, so the generic form scraper
    # ``_auto_authenticate`` can't follow it. The flow is well-documented
    # though: the initial HTML embeds a ``$Config`` JSON object that lists
    # the POST URL and CSRF/state tokens, and there's a small set of
    # endpoints we need to hit in order:
    #
    #   1. POST /common/GetCredentialType — username probe; tells us if
    #      the tenant is federated (redirect us to ADFS) or pure-cloud.
    #   2. POST $Config.urlPost — username + password.
    #   3. SAS / OneWaySMS / TOTP — MFA challenge if required, with the
    #      OTP from ``self.credentials.totp``.
    #   4. KMSI ("Stay signed in?") — auto-decline.
    #   5. The final response carries a ``<form action=ACS_URL>`` whose
    #      ``SAMLResponse`` field is the assertion the gateway expects;
    #      we POST it.
    #
    # This is what the user sees as the "I want everything in the console"
    # flow on issue #19. It's best-effort — Microsoft routinely changes
    # field names, MFA options, and conditional-access gates we can't
    # script (FIDO2, push, certificate auth). When something doesn't
    # match, we raise ``HeadlessAuthError`` so ``authenticate()`` can
    # surface the ``--browser chrome`` hint.
    def _auto_authenticate_entra(self, login_url, login_final_url, token_cookie_name):
        from lxml import html as lxml_html

        # Auto-extend the whitelist with login_url / login_final_url /
        # the Entra hosts the flow will redirect through.
        if self.allowed_hosts is not None:
            for url in (login_url, login_final_url):
                host = urlparse(url).hostname
                if host and host.lower() not in (h.lower() for h in self.allowed_hosts):
                    self.allowed_hosts.append(host)
            for h in _ENTRA_HOSTS:
                if h not in (e.lower() for e in self.allowed_hosts):
                    self.allowed_hosts.append(h)

        username = self.credentials.username
        password = self.credentials.password
        if not username or not password:
            raise HeadlessAuthError(
                "Scripted Entra login needs both username AND password "
                "available before connect (no interactive prompt in "
                "this path)."
            )
        totp = self.credentials.totp  # may be None — only required if MFA

        # 1. Initial GET — extract $Config{urlPost, sCtx, sFT, canary, ...}
        resp = self.session.get(login_url, timeout=self.timeout, allow_redirects=True)
        resp.raise_for_status()
        if not self._host_allowed(resp.url):
            raise HeadlessAuthError(
                f"Refusing to follow redirect to {urlparse(resp.url).hostname!r}"
            )
        cfg = self._parse_entra_config(resp.text)

        # 2. Probe credential type. If federated, the response carries a
        # ``FederationRedirectUrl`` we'd need to follow to ADFS / WS-Trust.
        # That branch isn't supported here yet; surface a clear error.
        gct_url = urljoin(resp.url, "/common/GetCredentialType")
        if not self._host_allowed(gct_url):
            raise HeadlessAuthError(
                f"Refusing to POST to {urlparse(gct_url).hostname!r} (not in allowed_hosts)"
            )
        gct_payload = {
            "username": username,
            "isOtherIdpSupported": True,
            "checkPhones": False,
            "isRemoteNGCSupported": True,
            "isCookieBannerShown": False,
            "isFidoSupported": True,
            "originalRequest": cfg.get("sCtx", ""),
            "country": cfg.get("country", ""),
            "forceotclogin": False,
            "isExternalFederationDisallowed": False,
            "isRemoteConnectSupported": False,
            "federationFlags": 0,
            "isSignup": False,
            "flowToken": cfg.get("sFT", ""),
        }
        gct_resp = self.session.post(
            gct_url,
            json=gct_payload,
            headers={"canary": cfg.get("canary", "")},
            timeout=self.timeout,
        )
        gct_resp.raise_for_status()
        gct = gct_resp.json()
        creds = gct.get("Credentials", {}) if isinstance(gct, dict) else {}
        if creds.get("FederationRedirectUrl"):
            # Federated tenant — route through ADFS / WS-Trust 2005.
            # Returns the response we should treat as if it had come
            # straight from the password POST (i.e. the next page in
            # the main flow). Experimental; logs a warning.
            logger.warning(
                "Federated MS Entra tenant detected — using experimental "
                "WS-Trust flow. If it fails, fall back to '--browser chrome'.",
                federation_redirect=creds["FederationRedirectUrl"],
            )
            resp = self._authenticate_via_ws_trust(
                username=username,
                password=password,
                user_realm_login=username,
            )
            # Hand off to the outer iteration loop — the wresult POST
            # to login.srf typically lands us on a SAMLResponse form.
            doc = lxml_html.fromstring(resp.content, base_url=resp.url)
            saml_token = self._submit_saml_response_form(doc, resp.url, token_cookie_name)
            if saml_token:
                return saml_token
            raise HeadlessAuthError(
                "WS-Trust flow completed but no SAMLResponse form was "
                "returned. The federated tenant may have additional "
                "MFA steps the scripted path can't drive."
            )
        # ``HasPassword=False`` typically means passwordless / FIDO2 only.
        if creds.get("HasPassword") is False:
            raise HeadlessAuthError(
                "Tenant doesn't accept username + password — likely passwordless / FIDO2 only."
            )
        flow_token = gct.get("FlowToken") or cfg.get("sFT", "")

        # 3. POST username + password to urlPost.
        url_post = cfg.get("urlPost") or urljoin(resp.url, "/common/login")
        if not url_post.startswith("http"):
            url_post = urljoin(resp.url, url_post)
        if not self._host_allowed(url_post):
            # ``urlPost`` is taken straight from a JSON blob in the page
            # body. A compromised / malformed page could point it at an
            # attacker-controlled host and exfiltrate the password we're
            # about to submit. Refuse to send credentials anywhere the
            # user's whitelist doesn't already cover.
            raise HeadlessAuthError(
                f"Refusing to POST credentials to "
                f"{urlparse(url_post).hostname!r} (not in allowed_hosts)"
            )
        login_payload = {
            "i13": "0",
            "login": username,
            "loginfmt": username,
            "type": "11",
            "LoginOptions": "3",
            "lrt": "",
            "lrtPartition": "",
            "hisRegion": "",
            "hisScaleUnit": "",
            "passwd": password,
            "ps": "2",
            "psRNGCDefaultType": "",
            "psRNGCEntropy": "",
            "psRNGCSLK": "",
            "canary": cfg.get("canary", ""),
            "ctx": cfg.get("sCtx", ""),
            "hpgrequestid": cfg.get("sessionId", ""),
            "flowToken": flow_token,
            "PPSX": "",
            "NewUser": "1",
            "FoundMSAs": "",
            "fspost": "0",
            "i21": "0",
            "CookieDisclosure": "0",
            "IsFidoSupported": "1",
            "isSignupPost": "0",
            "i19": "1",
        }
        resp = self.session.post(
            url_post,
            data=login_payload,
            timeout=self.timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # 4. Iterate: MFA / KMSI / SAML response form. Each step parses a
        # new $Config from the response and submits the next form.
        for step in range(8):
            # Did we already get a SAMLResponse form back to the gateway?
            doc = lxml_html.fromstring(resp.content, base_url=resp.url)
            saml_token = self._submit_saml_response_form(doc, resp.url, token_cookie_name)
            if saml_token:
                return saml_token

            # Wrong password? Microsoft signals via ``arrUserProofs`` /
            # ``urlMsaSignUp`` / a string in the page; cheapest test is
            # the page text.
            page_text = resp.text
            if (
                "Your account or password is incorrect" in page_text
                or "is not a valid email address" in page_text
                or '"sErrorCode":"50126"' in page_text
            ):
                raise HeadlessAuthError(
                    "Microsoft rejected the credentials (wrong username / password / locked out)."
                )

            # Each step of the flow can return a fresh ``urlPost``, and
            # each one needs the same whitelist check before we POST
            # session-bearing fields (TOTP, KMSI choice) to it. Also
            # validate ``resp.url`` after redirects landed us somewhere
            # — same threat model.
            if not self._host_allowed(resp.url):
                raise HeadlessAuthError(
                    f"Entra flow followed a redirect to "
                    f"{urlparse(resp.url).hostname!r} (not in allowed_hosts)"
                )
            cfg = self._parse_entra_config(page_text)
            url_post = cfg.get("urlPost") or resp.url
            if not url_post.startswith("http"):
                url_post = urljoin(resp.url, url_post)
            if not self._host_allowed(url_post):
                raise HeadlessAuthError(
                    f"Refusing to POST to {urlparse(url_post).hostname!r} (not in allowed_hosts)"
                )
            flow_token = cfg.get("sFT", flow_token)
            ctx = cfg.get("sCtx", "")

            # MFA — SAS endpoint expects an OTP code if we have one. The
            # sequence is BeginAuth → EndAuth → ProcessAuth, but for TOTP
            # the simplest working path is a direct POST to the same
            # urlPost with type=22 + otc=<code>.
            if totp and (
                "/common/SAS/" in page_text
                or "OneWaySMS" in page_text
                or '"sPollingUrl"' in page_text
                or '"sasPostUrl"' in page_text
                or "idTxtBx_SAOTCC_OTC" in page_text
            ):
                otc_payload = {
                    "type": "22",
                    "request": ctx,
                    "mfaAuthMethod": "PhoneAppOTP",
                    "otc": str(totp),
                    "login": username,
                    "flowToken": flow_token,
                    "hpgrequestid": cfg.get("sessionId", ""),
                    "canary": cfg.get("canary", ""),
                    "i19": "1",
                }
                resp = self.session.post(
                    url_post,
                    data=otc_payload,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                resp.raise_for_status()
                continue

            # KMSI — "Stay signed in?" page. Decline with LoginOptions=3.
            if "Kmsi" in page_text or "Stay signed in" in page_text:
                kmsi_payload = {
                    "LoginOptions": "3",
                    "type": "28",
                    "ctx": ctx,
                    "hpgrequestid": cfg.get("sessionId", ""),
                    "flowToken": flow_token,
                    "canary": cfg.get("canary", ""),
                    "i2": "1",
                    "i17": "",
                    "i18": "",
                    "i19": "1",
                }
                resp = self.session.post(
                    url_post,
                    data=kmsi_payload,
                    timeout=self.timeout,
                    allow_redirects=True,
                )
                resp.raise_for_status()
                continue

            # MFA challenge that we can't satisfy from CLI: FIDO2,
            # phone-call, push notification, "More information required".
            if "BeginAuth" in page_text and not totp:
                raise HeadlessAuthError(
                    "Tenant requires MFA but no TOTP secret is "
                    "available. Enrol the account's authenticator app "
                    "and pass the secret via keyring / `--totp-source`."
                )
            if (
                "FIDO" in page_text
                or "passkey" in page_text.lower()
                or "phoneAppNotification" in page_text
                or "ConvergedProofUpRedirect" in page_text
            ):
                raise HeadlessAuthError(
                    "Tenant requires an interactive MFA method that "
                    "can't be scripted from a console (FIDO2 key / "
                    "phone push / 'More info required')."
                )

            raise HeadlessAuthError(
                f"Unexpected page in Entra flow at step {step}: "
                f"no SAMLResponse, no known challenge."
            )

        raise HeadlessAuthError("Entra flow exceeded its step budget without a SAMLResponse")

    # -- ADFS / WS-Trust 2005 path (federated MS Entra tenants) -----------
    #
    # When ``GetCredentialType`` reports a tenant is federated, login
    # ceremonies don't happen at login.microsoftonline.com — they happen
    # at the customer's ADFS instance, which exposes a WS-Trust 2005
    # SOAP endpoint that swaps username + password for a SAML 1.1
    # assertion. We POST that assertion back to MS at /login.srf with
    # the ``wresult`` parameter, and from there the flow rejoins the
    # normal post-password page (which carries a SAML auto-submit form
    # bound for the SP / Cisco gateway).
    #
    # Documented under MS-MWBF and the ``msal-python`` source.
    # Best-effort and untested against a real federated tenant — the
    # caller logs a clear "experimental" warning and we fall back to
    # ``--browser chrome`` if anything in here surprises us.
    _WS_TRUST_NS = {
        "s": "http://www.w3.org/2003/05/soap-envelope",
        "wst": "http://docs.oasis-open.org/ws-sx/ws-trust/200512",
        "saml": "urn:oasis:names:tc:SAML:1.0:assertion",
    }

    def _authenticate_via_ws_trust(self, *, username, password, user_realm_login):
        """Drive a federated MS Entra tenant through ADFS / WS-Trust.

        Returns the ``requests.Response`` from the final POST to
        ``login.microsoftonline.com/login.srf`` so the caller can
        continue the regular Entra flow.
        """
        # 1. Realm discovery — tells us where the WS-Trust endpoint
        # lives. Returns JSON with ``AuthURL`` (WS-Trust 2005),
        # ``federation_protocol``, etc. ``user_realm_login`` is
        # URL-encoded so a ``+`` in an email alias survives intact
        # (raw ``+`` would be decoded as space by the server).
        realm_url = (
            "https://login.microsoftonline.com/getuserrealm.srf?"
            f"login={quote_plus(user_realm_login)}&xml=0"
        )
        if not self._host_allowed(realm_url):
            raise HeadlessAuthError(
                "Refusing to query realm-discovery on "
                f"{urlparse(realm_url).hostname!r} (not in allowed_hosts)"
            )
        realm_resp = self.session.get(realm_url, timeout=self.timeout)
        realm_resp.raise_for_status()
        realm = realm_resp.json() if hasattr(realm_resp, "json") else {}
        ws_trust_url = realm.get("AuthURL") or realm.get("auth_url")
        if not ws_trust_url:
            raise HeadlessAuthError(
                "Realm-discovery did not return a WS-Trust AuthURL — "
                "tenant federation config may be unusual."
            )
        # Reject anything but HTTPS — credentials are about to leave
        # the process and we won't send them in cleartext even if the
        # IdP is misconfigured.
        if urlparse(ws_trust_url).scheme != "https":
            raise HeadlessAuthError(
                f"WS-Trust AuthURL {ws_trust_url!r} is not HTTPS; "
                "refusing to send credentials over an unencrypted channel."
            )
        if not self._host_allowed(ws_trust_url):
            raise HeadlessAuthError(
                f"WS-Trust endpoint host {urlparse(ws_trust_url).hostname!r} "
                "is not in allowed_hosts; refusing to send credentials "
                "to it."
            )

        # 2. Build + POST SOAP envelope. ADFS validates user/pwd and
        # returns a SAML 1.1 assertion wrapped in an RSTR. We disable
        # automatic redirect-following on this leg specifically: any
        # 30x response would re-POST the credentials to the redirect
        # target, and we don't want to authorise that destination
        # implicitly. If a redirect is required, the IdP needs to be
        # configured to point ``AuthURL`` at the final endpoint.
        soap_body = self._ws_trust_soap_envelope(
            username=username,
            password=password,
            ws_trust_url=ws_trust_url,
        )
        wst_resp = self.session.post(
            ws_trust_url,
            data=soap_body.encode("utf-8"),
            headers={
                "Content-Type": "application/soap+xml; charset=utf-8",
                "SOAPAction": ("http://docs.oasis-open.org/ws-sx/ws-trust/200512/RST/Issue"),
            },
            timeout=self.timeout,
            allow_redirects=False,
        )
        if 300 <= wst_resp.status_code < 400:
            raise HeadlessAuthError(
                f"WS-Trust endpoint returned a {wst_resp.status_code} redirect; "
                "refusing to follow because credentials were just POSTed."
            )
        wst_resp.raise_for_status()

        # 3. Extract the SAML 1.1 assertion (xml fragment).
        from lxml import etree as lxml_etree

        try:
            root = lxml_etree.fromstring(wst_resp.content)
        except lxml_etree.XMLSyntaxError as exc:
            raise HeadlessAuthError(f"WS-Trust response wasn't valid XML: {exc}") from exc
        assertions = root.findall(".//{urn:oasis:names:tc:SAML:1.0:assertion}Assertion")
        if not assertions:
            # Some ADFS error responses are well-formed SOAP faults —
            # surface the fault text if we can find one.
            faults = root.findall(".//{*}Reason") + root.findall(".//{*}Text")
            fault_text = next((f.text for f in faults if f.text), "no fault text")
            raise HeadlessAuthError(f"ADFS rejected the credentials: {fault_text}")
        assertion_xml = lxml_etree.tostring(assertions[0]).decode("utf-8")

        # 4. POST the assertion to login.srf as ``wresult``. Microsoft
        # then issues federated-auth cookies; the response is the
        # post-password page that the main flow expects.
        login_srf = "https://login.microsoftonline.com/login.srf"
        if not self._host_allowed(login_srf):
            raise HeadlessAuthError(
                "Refusing to POST WS-Trust assertion to "
                f"{urlparse(login_srf).hostname!r} (not in allowed_hosts)"
            )
        return self.session.post(
            login_srf,
            data={
                "wa": "wsignin1.0",
                "wresult": (
                    "<t:RequestSecurityTokenResponse "
                    'xmlns:t="http://schemas.xmlsoap.org/ws/2005/02/trust">'
                    f"{assertion_xml}"
                    "</t:RequestSecurityTokenResponse>"
                ),
                "wctx": "",
            },
            timeout=self.timeout,
            allow_redirects=True,
        )

    @classmethod
    def _ws_trust_soap_envelope(cls, *, username, password, ws_trust_url):
        """Build the WS-Trust 2005 RST envelope. Username + password
        go into a UsernameToken; the AppliesTo URI is fixed to MS's
        federation realm."""
        import html as html_mod
        import uuid

        msg_id = f"urn:uuid:{uuid.uuid4()}"
        u = html_mod.escape(username)
        p = html_mod.escape(password)
        # The realm-discovery response is server-controlled; XML-escape
        # it before splicing into ``<a:To>`` so a hostile / malformed
        # URL can't break out of the attribute or inject extra elements.
        addr_to = html_mod.escape(ws_trust_url, quote=True)
        return (
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:a="http://www.w3.org/2005/08/addressing" '
            'xmlns:o="http://docs.oasis-open.org/wss/2004/01/'
            'oasis-200401-wss-wssecurity-secext-1.0.xsd">'
            "<s:Header>"
            '<a:Action s:mustUnderstand="1">'
            "http://docs.oasis-open.org/ws-sx/ws-trust/200512/RST/Issue"
            "</a:Action>"
            f"<a:MessageID>{msg_id}</a:MessageID>"
            "<a:ReplyTo><a:Address>http://www.w3.org/2005/08/addressing/anonymous"
            "</a:Address></a:ReplyTo>"
            f'<a:To s:mustUnderstand="1">{addr_to}</a:To>'
            '<o:Security s:mustUnderstand="1">'
            "<o:UsernameToken>"
            f"<o:Username>{u}</o:Username>"
            f"<o:Password>{p}</o:Password>"
            "</o:UsernameToken>"
            "</o:Security>"
            "</s:Header>"
            "<s:Body>"
            "<trust:RequestSecurityToken "
            'xmlns:trust="http://docs.oasis-open.org/ws-sx/ws-trust/200512">'
            '<wsp:AppliesTo xmlns:wsp="http://schemas.xmlsoap.org/ws/2004/09/policy">'
            "<wsa:EndpointReference "
            'xmlns:wsa="http://www.w3.org/2005/08/addressing">'
            "<wsa:Address>urn:federation:MicrosoftOnline</wsa:Address>"
            "</wsa:EndpointReference>"
            "</wsp:AppliesTo>"
            "<trust:KeyType>"
            "http://docs.oasis-open.org/ws-sx/ws-trust/200512/Bearer"
            "</trust:KeyType>"
            "<trust:RequestType>"
            "http://docs.oasis-open.org/ws-sx/ws-trust/200512/Issue"
            "</trust:RequestType>"
            "</trust:RequestSecurityToken>"
            "</s:Body>"
            "</s:Envelope>"
        )

    def _parse_entra_config(self, html_text):
        """Pull the embedded ``$Config = {...}`` JSON out of an Entra
        login page. Returns a dict with at least ``urlPost``, ``sCtx``,
        ``sFT``, ``canary`` if the page is a real Entra login page.
        Returns ``{}`` otherwise.
        """
        import json
        import re

        m = re.search(r"\$Config\s*=\s*(\{.+?\});", html_text, re.DOTALL)
        if not m:
            return {}
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _submit_saml_response_form(self, doc, base_url, token_cookie_name):
        """If ``doc`` carries a SAMLResponse auto-submit form, post it
        to its action URL, then read the SSO cookie back. Returns the
        token if found, ``None`` if no SAML form is present.
        """
        for form in doc.forms:
            fields = dict(form.fields) if hasattr(form.fields, "items") else {}
            if "SAMLResponse" not in fields:
                continue
            # Default the action to the page's own URL if the form
            # didn't set one (some IdPs emit ``<form action="">`` and
            # rely on the browser to use the current document URL).
            action = form.action or base_url
            if not action.startswith("http"):
                action = urljoin(base_url, action)
            # Same threat model as urlPost: never POST a SAML assertion
            # to a host the user's whitelist doesn't already cover.
            if not self._host_allowed(action):
                raise HeadlessAuthError(
                    f"Refusing to POST SAMLResponse to "
                    f"{urlparse(action).hostname!r} (not in allowed_hosts)"
                )
            resp = self.session.post(
                action,
                data=fields,
                timeout=self.timeout,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return self._extract_token(resp, token_cookie_name) or self._check_cookies_for_token(
                token_cookie_name
            )
        return None

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
        result = {"token": None, "error": None}  # nosec
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

    def _run_auth_script(self, login_url, login_final_url, token_cookie_name):
        """Run the external auth script and return the SSO token from stdout.

        The script is invoked as:
            <script_path> <login_url> <token_cookie_name> <username>

        The password is fed to the script's stdin (one line, no trailing
        newline added). The script must print the SSO token to stdout.
        Stderr is captured for logging/debugging but not parsed.

        Environment is restricted to ``PATH`` and ``HOME`` only — the
        script doesn't need to inherit our potentially-sensitive env
        (``REQUESTS_CA_BUNDLE``, AWS credentials, keyring tokens, …).
        Add what you need explicitly inside the script.

        Returns the token string, or raises HeadlessAuthError on failure.
        """
        import os as _os

        username = self.credentials.username
        script_path = self.auth_script
        cmd = [script_path, login_url, token_cookie_name, username]

        # Minimal env: PATH so common tools resolve, HOME for ssh / pass /
        # gnupg / gpg-agent that scripts often shell out to. Anything else
        # the script needs has to be set inside the script.
        env = {
            "PATH": _os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": _os.environ.get("HOME", ""),
        }

        # Don't log the cmd at INFO — it contains the username (and the
        # path to the user's auth script which is itself a hint about
        # their setup). DEBUG is fine.
        logger.debug("Running auth script", script=script_path)

        try:
            result = subprocess.run(  # nosec — script is user-supplied, by design
                cmd,
                input=self.credentials.password,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
        except FileNotFoundError:
            raise HeadlessAuthError(
                f"Auth script not found: {script_path!r}. "
                "Check the path and ensure the script is executable."
            ) from None
        except subprocess.TimeoutExpired:
            raise HeadlessAuthError(f"Auth script timed out after {self.timeout}s") from None

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise HeadlessAuthError(
                f"Auth script exited with code {result.returncode}: {stderr or 'no stderr output'}"
            )

        token = result.stdout.strip()
        if not token:
            raise HeadlessAuthError("Auth script produced empty stdout (no token)")

        logger.info(
            "Auth script returned token",
            script=script_path,
            token_length=len(token),
        )
        return token
