"""Security regression: auth request/response bodies must never be logged
verbatim at DEBUG (audit SEC-01 / INFO-04).

The auth *finish* request embeds the SSO token and the finish response
carries the VPN session token. Logging either body at --log-level DEBUG
would write a replayable credential to stderr/log files.
"""

from unittest.mock import MagicMock, patch

from openconnect_saml.authenticator import Authenticator

SESSION_TOKEN = "SUPER-SECRET-SESSION-TOKEN-9f8e7d"
SSO_TOKEN = "SSO-SECRET-aabbccdd"


def _make_authenticator():
    host = MagicMock()
    host.vpn_url = "https://vpn.example.com"
    host.name = "vpn"
    host.address = "https://vpn.example.com"
    with patch("openconnect_saml.authenticator.create_http_session"):
        auth = Authenticator(host, version="4.7.00136")
    auth.session = MagicMock()
    return auth


def _all_logged_strings(mock_logger):
    """Flatten every positional + keyword value passed to logger.debug."""
    chunks = []
    for call in mock_logger.debug.call_args_list:
        chunks.extend(str(a) for a in call.args)
        chunks.extend(str(v) for v in call.kwargs.values())
    return " || ".join(chunks)


class TestAuthFinishLogRedaction:
    @patch("openconnect_saml.authenticator.parse_response", return_value=MagicMock())
    @patch(
        "openconnect_saml.authenticator._create_auth_finish_request",
        return_value=f"<finish>{SSO_TOKEN}</finish>",
    )
    @patch("openconnect_saml.authenticator.logger")
    def test_finish_does_not_log_token_bodies(self, mock_logger, mock_req, mock_parse):
        auth = _make_authenticator()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = f"<auth><session-token>{SESSION_TOKEN}</session-token></auth>".encode()
        auth.session.post.return_value = resp

        auth._complete_authentication(MagicMock(), SSO_TOKEN)

        logged = _all_logged_strings(mock_logger)
        assert SESSION_TOKEN not in logged, "session token leaked into DEBUG logs"
        assert SSO_TOKEN not in logged, "SSO token leaked into DEBUG logs"
        # Breadcrumb metadata is still logged so DEBUG stays useful.
        kwargs_keys = {k for c in mock_logger.debug.call_args_list for k in c.kwargs}
        assert "response_bytes" in kwargs_keys
        assert "request_bytes" in kwargs_keys

    @patch("openconnect_saml.authenticator.parse_response", return_value=MagicMock())
    @patch(
        "openconnect_saml.authenticator._create_auth_init_request",
        return_value="<init>request</init>",
    )
    @patch("openconnect_saml.authenticator.logger")
    def test_init_does_not_log_raw_bodies(self, mock_logger, mock_req, mock_parse):
        auth = _make_authenticator()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"<init-response>login-url-and-saml-state</init-response>"
        auth.session.post.return_value = resp

        auth._start_authentication()

        logged = _all_logged_strings(mock_logger)
        assert "login-url-and-saml-state" not in logged
        assert "<init>request</init>" not in logged
