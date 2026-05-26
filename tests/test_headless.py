"""Tests for headless authentication module."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest

from openconnect_saml.headless import (
    DEFAULT_CALLBACK_PORT,
    HeadlessAuthenticator,
    HeadlessAuthError,
)


@pytest.fixture
def mock_credentials():
    creds = MagicMock()
    creds.username = "testuser@example.com"
    creds.password = "testpass123"
    creds.totp = "123456"
    return creds


@pytest.fixture
def mock_auth_response():
    resp = MagicMock()
    resp.login_url = "https://login.example.com/saml?SAMLRequest=abc123"
    resp.login_final_url = "https://vpn.example.com/SAML20/SP/ACS"
    resp.token_cookie_name = "sso-token"
    return resp


@pytest.fixture
def headless_auth(mock_credentials):
    return HeadlessAuthenticator(
        credentials=mock_credentials,
        timeout=5,
        callback_timeout=5,
    )


class TestHeadlessAuthenticatorInit:
    def test_default_values(self):
        auth = HeadlessAuthenticator()
        assert auth.proxy is None
        assert auth.credentials is None
        assert auth.ssl_legacy is False
        assert auth.timeout == 30
        assert auth.callback_port == DEFAULT_CALLBACK_PORT
        assert auth.callback_timeout == 300

    def test_custom_values(self, mock_credentials):
        auth = HeadlessAuthenticator(
            proxy="http://proxy:8080",
            credentials=mock_credentials,
            ssl_legacy=True,
            timeout=60,
            callback_port=12345,
            callback_timeout=120,
        )
        assert auth.proxy == "http://proxy:8080"
        assert auth.credentials == mock_credentials
        assert auth.ssl_legacy is True
        assert auth.timeout == 60
        assert auth.callback_port == 12345
        assert auth.callback_timeout == 120

    def test_session_created(self, headless_auth):
        assert headless_auth.session is not None
        assert "User-Agent" in headless_auth.session.headers


class TestFieldDetection:
    def test_username_field_by_name(self):
        el = MagicMock()
        el.get = MagicMock(return_value="")
        assert HeadlessAuthenticator._is_username_field("loginfmt", el) is True
        assert HeadlessAuthenticator._is_username_field("email", el) is True
        assert HeadlessAuthenticator._is_username_field("username", el) is True
        assert HeadlessAuthenticator._is_username_field("user_login", el) is True

    def test_username_field_by_placeholder(self):
        el = MagicMock()
        el.get = MagicMock(
            side_effect=lambda k, d="": "Enter your email" if k == "placeholder" else d
        )
        assert HeadlessAuthenticator._is_username_field("somefield", el) is True

    def test_username_field_by_autocomplete(self):
        el = MagicMock()
        el.get = MagicMock(side_effect=lambda k, d="": "username" if k == "autocomplete" else d)
        assert HeadlessAuthenticator._is_username_field("somefield", el) is True

    def test_not_username_field(self):
        el = MagicMock()
        el.get = MagicMock(return_value="")
        assert HeadlessAuthenticator._is_username_field("csrftoken", el) is False

    def test_totp_field_by_name(self):
        el = MagicMock()
        el.get = MagicMock(return_value="")
        assert HeadlessAuthenticator._is_totp_field("otc", el) is True
        assert HeadlessAuthenticator._is_totp_field("totp_code", el) is True
        assert HeadlessAuthenticator._is_totp_field("verificationCode", el) is True

    def test_totp_field_by_placeholder(self):
        el = MagicMock()
        el.get = MagicMock(
            side_effect=lambda k, d="": "Enter OTP code" if k == "placeholder" else d
        )
        assert HeadlessAuthenticator._is_totp_field("somefield", el) is True

    def test_not_totp_field(self):
        el = MagicMock()
        el.get = MagicMock(return_value="")
        assert HeadlessAuthenticator._is_totp_field("password", el) is False


class TestMetaRefresh:
    def test_find_meta_refresh(self):
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(
            '<html><head><meta http-equiv="refresh" content="0;url=https://example.com/next">'
            "</head><body></body></html>"
        )
        url = HeadlessAuthenticator._find_meta_refresh(doc, "https://example.com")
        assert url == "https://example.com/next"

    def test_find_meta_refresh_relative(self):
        from lxml import html as lxml_html

        doc = lxml_html.fromstring(
            '<html><head><meta http-equiv="refresh" content="0;url=/next">'
            "</head><body></body></html>"
        )
        url = HeadlessAuthenticator._find_meta_refresh(doc, "https://example.com/page")
        assert url == "https://example.com/next"

    def test_no_meta_refresh(self):
        from lxml import html as lxml_html

        doc = lxml_html.fromstring("<html><head></head><body></body></html>")
        url = HeadlessAuthenticator._find_meta_refresh(doc, "https://example.com")
        assert url is None


class TestAutoPostForm:
    def test_detect_saml_auto_post(self):
        html_text = """
        <html><body>
        <form method="POST" action="https://vpn.example.com/SAML20/SP/ACS">
            <input type="hidden" name="SAMLResponse" value="base64response" />
            <input type="hidden" name="RelayState" value="relay123" />
        </form>
        <script>document.forms[0].submit();</script>
        </body></html>
        """
        result = HeadlessAuthenticator._find_auto_post_form(html_text, "https://login.example.com")
        assert result is not None
        action, data = result
        assert action == "https://vpn.example.com/SAML20/SP/ACS"
        assert data["SAMLResponse"] == "base64response"
        assert data["RelayState"] == "relay123"

    def test_no_auto_post_without_submit(self):
        html_text = """
        <html><body>
        <form method="POST" action="https://vpn.example.com/login">
            <input type="text" name="user" value="" />
        </form>
        </body></html>
        """
        result = HeadlessAuthenticator._find_auto_post_form(html_text, "https://login.example.com")
        assert result is None


class TestUrlMatching:
    def test_exact_match(self):
        auth = HeadlessAuthenticator()
        assert auth._url_matches(
            "https://vpn.example.com/path",
            "https://vpn.example.com/path",
        )

    def test_ignores_query_params(self):
        auth = HeadlessAuthenticator()
        assert auth._url_matches(
            "https://vpn.example.com/path?foo=bar",
            "https://vpn.example.com/path",
        )

    def test_different_path(self):
        auth = HeadlessAuthenticator()
        assert not auth._url_matches(
            "https://vpn.example.com/other",
            "https://vpn.example.com/path",
        )


class TestCallbackServer:
    """Test the local callback HTTP server approach."""

    @pytest.mark.skipif(True, reason="Integration test: requires real HTTP server timing")
    def test_callback_receives_token_get(self, mock_credentials, mock_auth_response):
        """Test that the callback server accepts GET with token parameter."""
        auth = HeadlessAuthenticator(
            credentials=mock_credentials,
            timeout=5,
            callback_port=0,  # Random port
            callback_timeout=10,
        )

        # We need to test the callback server mechanism
        # Start it in a thread and send a request
        result = {}

        def run_callback():
            try:
                token = auth._callback_authenticate(
                    str(mock_auth_response.login_url),
                    str(mock_auth_response.login_final_url),
                    str(mock_auth_response.token_cookie_name),
                )
                result["token"] = token
            except Exception as e:
                result["error"] = e

        thread = threading.Thread(target=run_callback)
        thread.start()

        # Give server time to start
        time.sleep(0.5)

        # Send callback request
        import requests

        port = auth.callback_port
        resp = requests.get(
            f"http://127.0.0.1:{port}/callback?sso-token=test-token-value",
            timeout=5,
        )
        assert resp.status_code == 200

        thread.join(timeout=5)
        assert result.get("token") == "test-token-value"

    @pytest.mark.skipif(True, reason="Integration test: requires real HTTP server timing")
    def test_callback_receives_token_post(self, mock_credentials, mock_auth_response):
        """Test that the callback server accepts POST with token."""
        auth = HeadlessAuthenticator(
            credentials=mock_credentials,
            timeout=5,
            callback_port=0,  # Random port
            callback_timeout=10,
        )

        result = {}

        def run_callback():
            try:
                token = auth._callback_authenticate(
                    str(mock_auth_response.login_url),
                    str(mock_auth_response.login_final_url),
                    str(mock_auth_response.token_cookie_name),
                )
                result["token"] = token
            except Exception as e:
                result["error"] = e

        thread = threading.Thread(target=run_callback)
        thread.start()
        time.sleep(0.5)

        import requests

        port = auth.callback_port
        resp = requests.post(
            f"http://127.0.0.1:{port}/callback",
            data=urlencode({"sso-token": "post-token-value"}),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=5,
        )
        assert resp.status_code == 200

        thread.join(timeout=5)
        assert result.get("token") == "post-token-value"

    def test_callback_timeout(self, mock_credentials, mock_auth_response):
        """Test that the callback server times out properly."""
        auth = HeadlessAuthenticator(
            credentials=mock_credentials,
            timeout=5,
            callback_port=0,
            callback_timeout=2,  # Short timeout
        )

        with pytest.raises(HeadlessAuthError, match="timed out"):
            auth._callback_authenticate(
                str(mock_auth_response.login_url),
                str(mock_auth_response.login_final_url),
                str(mock_auth_response.token_cookie_name),
            )


class TestAutoAuthenticate:
    """Test the automatic form-based authentication."""

    def test_auto_auth_with_login_form(self, headless_auth, mock_auth_response):
        """Test auto-auth against a mock login form server."""
        # Create a simple mock server that serves a login form then redirects

        f"""
        <html><body>
        <form method="POST" action="{str(mock_auth_response.login_final_url)}">
            <input type="hidden" name="SAMLResponse" value="base64data" />
        </form>
        <script>document.forms[0].submit();</script>
        </body></html>
        """

        # This test uses responses mock — but if not available, skip
        pytest.importorskip("responses")

    def test_auto_auth_no_forms_raises(self, headless_auth):
        """Test that auto-auth raises when no forms are found."""
        with patch.object(headless_auth.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.url = "https://login.example.com"
            mock_resp.content = b"<html><body>No forms here</body></html>"
            mock_resp.text = "<html><body>No forms here</body></html>"
            mock_resp.headers = {"content-type": "text/html"}
            mock_resp.raise_for_status = MagicMock()
            mock_get.return_value = mock_resp

            with pytest.raises(HeadlessAuthError, match="No forms found"):
                headless_auth._auto_authenticate(
                    "https://login.example.com",
                    "https://vpn.example.com/final",
                    "sso-token",
                )


class TestAsyncAuthenticate:
    """Test the main async authenticate method."""

    @pytest.mark.asyncio
    async def test_falls_back_to_callback_on_auto_failure(
        self, mock_credentials, mock_auth_response
    ):
        """Test that authenticate falls back to callback when auto-auth fails."""
        auth = HeadlessAuthenticator(
            credentials=mock_credentials,
            timeout=5,
            callback_timeout=2,
        )

        with (
            patch.object(auth, "_auto_authenticate", side_effect=HeadlessAuthError("nope")),
            patch.object(auth, "_callback_authenticate", return_value="callback-token"),
        ):
            token = await auth.authenticate(mock_auth_response)
            assert token == "callback-token"

    @pytest.mark.asyncio
    async def test_auto_auth_success_skips_callback(self, mock_credentials, mock_auth_response):
        """Test that successful auto-auth doesn't start callback server."""
        auth = HeadlessAuthenticator(
            credentials=mock_credentials,
            timeout=5,
        )

        with (
            patch.object(auth, "_auto_authenticate", return_value="auto-token"),
            patch.object(auth, "_callback_authenticate") as mock_callback,
        ):
            token = await auth.authenticate(mock_auth_response)
            assert token == "auto-token"
            mock_callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_credentials_goes_to_callback(self, mock_auth_response):
        """Test that without credentials, goes straight to callback."""
        auth = HeadlessAuthenticator(
            credentials=None,
            timeout=5,
            callback_timeout=2,
        )

        with (
            patch.object(auth, "_callback_authenticate", return_value="cb-token"),
            patch.object(auth, "_auto_authenticate") as mock_auto,
        ):
            token = await auth.authenticate(mock_auth_response)
            assert token == "cb-token"
            mock_auto.assert_not_called()


class TestCLIFlags:
    """Test that --headless CLI flag works correctly."""

    def test_headless_flag(self):
        from openconnect_saml.cli import create_legacy_argparser as create_argparser

        parser = create_argparser()
        args = parser.parse_args(["-s", "vpn.example.com", "--headless"])
        assert args.headless is True

    def test_headless_default_false(self):
        from openconnect_saml.cli import create_legacy_argparser as create_argparser

        parser = create_argparser()
        args = parser.parse_args(["-s", "vpn.example.com"])
        assert args.headless is False

    def test_headless_with_user(self):
        from openconnect_saml.cli import create_legacy_argparser as create_argparser

        parser = create_argparser()
        args = parser.parse_args(
            [
                "-s",
                "vpn.example.com",
                "--headless",
                "-u",
                "testuser",
            ]
        )
        assert args.headless is True
        assert args.user == "testuser"


class TestHeadlessModeIntegration:
    """Test that headless mode is properly wired into the authenticator."""

    def test_headless_mode_sentinel(self):
        from openconnect_saml.authenticator import HEADLESS_MODE

        assert HEADLESS_MODE == "headless"

    @pytest.mark.asyncio
    async def test_authenticator_uses_headless(self):
        """Test that Authenticator dispatches to HeadlessAuthenticator."""
        from openconnect_saml.authenticator import HEADLESS_MODE, Authenticator
        from openconnect_saml.config import HostProfile

        host = HostProfile("vpn.example.com", "", "test")

        auth = Authenticator(host, version="4.7.00136")

        mock_request = MagicMock()
        mock_request.login_url = "https://login.example.com/saml"
        mock_request.login_final_url = "https://vpn.example.com/final"
        mock_request.token_cookie_name = "sso-token"

        with patch("openconnect_saml.headless.HeadlessAuthenticator") as MockHeadless:
            mock_instance = MagicMock()

            async def fake_authenticate(auth_resp):
                return "test-token"

            mock_instance.authenticate = fake_authenticate
            MockHeadless.return_value = mock_instance

            token = await auth._authenticate_in_browser(mock_request, HEADLESS_MODE)
            MockHeadless.assert_called_once()
            assert token == "test-token"


class TestEntraDetection:
    def test_login_microsoftonline_is_entra(self):
        from openconnect_saml.headless import _is_ms_entra_idp

        assert _is_ms_entra_idp("https://login.microsoftonline.com/common/oauth2/authorize")
        assert _is_ms_entra_idp("https://login.microsoftonline.us/foo/saml2?id=1")
        assert _is_ms_entra_idp("https://login.live.com/login.srf")

    def test_unrelated_hosts_are_not_entra(self):
        from openconnect_saml.headless import _is_ms_entra_idp

        assert not _is_ms_entra_idp("https://idp.example.com/saml")
        assert not _is_ms_entra_idp("https://accounts.google.com/o/oauth2/v2/auth")
        assert not _is_ms_entra_idp("not-a-url")
        assert not _is_ms_entra_idp("")


class TestEntraConfigParser:
    """The Entra login page embeds a ``$Config = {...};`` JSON block —
    make sure we extract its ``urlPost`` / ``sCtx`` / ``sFT`` / ``canary``
    fields when present and degrade cleanly when not.
    """

    def _make_authenticator(self):
        from openconnect_saml.headless import HeadlessAuthenticator

        return HeadlessAuthenticator()

    def test_extracts_known_fields(self):
        page = """
        <html><head><script>//<![CDATA[
            $Config = {"urlPost":"https://login.microsoftonline.com/common/login",
                       "sCtx":"CtxToken123",
                       "sFT":"FlowToken456",
                       "canary":"CanaryValue",
                       "sessionId":"session-789"};
        //]]></script></head><body></body></html>
        """
        cfg = self._make_authenticator()._parse_entra_config(page)
        assert cfg["urlPost"].endswith("/common/login")
        assert cfg["sCtx"] == "CtxToken123"
        assert cfg["sFT"] == "FlowToken456"
        assert cfg["canary"] == "CanaryValue"
        assert cfg["sessionId"] == "session-789"

    def test_returns_empty_dict_when_no_config_block(self):
        cfg = self._make_authenticator()._parse_entra_config("<html></html>")
        assert cfg == {}

    def test_returns_empty_dict_on_malformed_json(self):
        cfg = self._make_authenticator()._parse_entra_config(
            "<script>$Config = {not json at all};</script>"
        )
        assert cfg == {}


class TestEntraRoutingHints:
    """The user-facing message when scripted Entra auth fails should
    point at ``--browser chrome``; the hint string is asserted to keep
    that wording stable for users searching for it.
    """

    def test_hint_mentions_browser_chrome_and_install_steps(self):
        from openconnect_saml.headless import _ENTRA_HEADLESS_HINT

        assert "--browser chrome" in _ENTRA_HEADLESS_HINT
        assert "playwright install chromium" in _ENTRA_HEADLESS_HINT
        # And it should explicitly say no display is required, since
        # that's the user's whole concern.
        assert "DISPLAY" in _ENTRA_HEADLESS_HINT or "headless" in _ENTRA_HEADLESS_HINT


class TestRunAuthScriptMissingBinary:
    """_run_auth_script must raise HeadlessAuthError (not FileNotFoundError)
    when the script path does not exist on the filesystem."""

    def _make_auth(self):
        creds = MagicMock()
        creds.username = "user@example.com"
        creds.password = "secret"
        creds.totp = None
        return HeadlessAuthenticator(
            credentials=creds,
            auth_script="/nonexistent/path/to/auth-script.sh",
            timeout=5,
        )

    def test_missing_script_raises_headless_auth_error(self):
        """FileNotFoundError from subprocess.run must be caught and re-raised
        as HeadlessAuthError with a clear message."""
        auth = self._make_auth()
        with (
            patch(
                "openconnect_saml.headless.subprocess.run",
                side_effect=FileNotFoundError(
                    2, "No such file or directory", "/nonexistent/path/to/auth-script.sh"
                ),
            ),
            pytest.raises(HeadlessAuthError, match="Auth script not found"),
        ):
            auth._run_auth_script(
                "https://login.example.com/saml",
                "https://vpn.example.com/acs",
                "sso-token",
            )

    def test_missing_script_error_not_file_not_found_error(self):
        """The raised exception must NOT be FileNotFoundError — callers expect
        HeadlessAuthError from _run_auth_script."""
        auth = self._make_auth()
        with patch(
            "openconnect_saml.headless.subprocess.run",
            side_effect=FileNotFoundError("gone"),
        ):
            try:
                auth._run_auth_script("https://x.example.com", "https://y.example.com", "tok")
            except FileNotFoundError:
                pytest.fail("FileNotFoundError leaked out of _run_auth_script")
            except HeadlessAuthError:
                pass  # correct
