"""Mock Cisco-AnyConnect gateway with SAML SSO + paired SAML IdP.

Implements just enough of the protocol for openconnect-saml to drive a
full authentication flow against a localhost server:

1. ``POST /`` with ``<config-auth type="init">`` → returns an
   ``auth-request`` XML pointing at the bundled mock IdP.
2. ``GET /login`` (mock IdP path) → returns an HTML form with a
   ``username`` + ``password`` field. Submitting it sets a cookie
   containing the SSO token and redirects back to the gateway.
3. ``GET /+CSCOE+/saml/sp/acs`` (gateway) → finalises the SAML
   handshake and sets the ``webvpn`` cookie that openconnect-saml
   harvests as the SSO token.
4. ``POST /`` with ``<config-auth type="auth-reply">`` carrying the
   SSO token → returns ``auth-complete`` XML with a session cookie
   and a server-cert hash placeholder.

The harness runs over HTTPS with an on-the-fly self-signed cert,
mirroring the real flow (certificate hash gets pinned via
``--servercert`` from the auth-complete response).

Usage from a test:

    with MockGateway() as gw:
        # gw.url is the public base URL, e.g. https://localhost:48xxx
        ...

The class exposes ``request_log`` for assertions on what the client
actually sent.
"""

from __future__ import annotations

import datetime
import socket
import ssl
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

# A canned SSO token the gateway hands back to the client. Real gateways
# generate per-session strings; we hard-code one so tests can assert on it.
SSO_TOKEN = "TEST-SSO-TOKEN-12345"
# The auth-complete response carries a session token + cert-hash placeholder.
SESSION_TOKEN = "TEST-SESSION-TOKEN-67890"
CERT_HASH_PLACEHOLDER = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _generate_self_signed_cert(host: str = "localhost") -> tuple[Path, Path]:
    """Produce (cert_pem_path, key_pem_path) for a fresh self-signed cert."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow())
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(host), x509.DNSName("127.0.0.1")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    tmp = Path(tempfile.mkdtemp(prefix="oc-saml-mock-"))
    cert_path = tmp / "cert.pem"
    key_path = tmp / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _free_port() -> int:
    """Pick an unused TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Handler(BaseHTTPRequestHandler):
    """HTTP handler covering both the gateway and the mock IdP."""

    # Set by MockGateway after construction so the handler can find the parent.
    server_owner: MockGateway = None  # type: ignore[assignment]

    def log_message(self, fmt, *args):  # noqa: D401
        # Quiet by default — tests can opt into verbose logging via the parent.
        if self.server_owner and self.server_owner.verbose:
            super().log_message(fmt, *args)

    # -- gateway endpoints ------------------------------------------------

    def do_POST(self):  # noqa: N802 — http.server convention
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        self.server_owner.request_log.append({"method": "POST", "path": self.path, "body": body})

        if self.path == "/" or self.path == "":
            self._handle_config_auth(body)
            return
        if self.path == "/+CSCOE+/saml/sp/acs":
            # IdP posted the form back here with credentials → set webvpn cookie
            self._handle_saml_acs(body)
            return
        self._respond(404, "text/plain", b"not found")

    def do_GET(self):  # noqa: N802
        self.server_owner.request_log.append({"method": "GET", "path": self.path, "body": b""})

        if self.path.startswith("/login"):
            self._serve_login_form()
            return
        if self.path.startswith("/+CSCOE+/saml/sp/acs"):
            # Some flows do a GET here after the IdP redirect. Set the cookie
            # and respond with the success page.
            self._handle_saml_acs(b"")
            return
        # Default GET: just confirm the gateway is alive (used by probes).
        self._respond(200, "text/html", b"<html><body>mock gateway</body></html>")

    # -- handlers ---------------------------------------------------------

    def _handle_config_auth(self, body: bytes):
        """Reply to the AnyConnect XML auth-init / auth-reply requests."""
        text = body.decode("utf-8", errors="replace")
        if 'type="init"' in text:
            login_url = f"{self.server_owner.url}/login"
            login_final_url = f"{self.server_owner.url}/+CSCOE+/saml/sp/acs"
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<config-auth client="vpn" type="auth-request" '
                'aggregate-auth-version="2">\n'
                '  <auth id="main">\n'
                "    <title>Mock Gateway</title>\n"
                "    <message>Please authenticate</message>\n"
                f"    <sso-v2-login>{login_url}</sso-v2-login>\n"
                f"    <sso-v2-login-final>{login_final_url}</sso-v2-login-final>\n"
                "    <sso-v2-token-cookie-name>webvpn</sso-v2-token-cookie-name>\n"
                "  </auth>\n"
                "  <opaque/>\n"
                "</config-auth>\n"
            )
            self._respond(200, "text/xml", xml.encode("utf-8"))
            return
        if 'type="auth-reply"' in text:
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<config-auth client="vpn" type="complete" '
                'aggregate-auth-version="2">\n'
                '  <auth id="success"><message>Logged in</message></auth>\n'
                f"  <session-token>{SESSION_TOKEN}</session-token>\n"
                "  <session-id>session-1</session-id>\n"
                "  <config>\n"
                "    <vpn-base-config>\n"
                f"      <server-cert-hash>{CERT_HASH_PLACEHOLDER}"
                "</server-cert-hash>\n"
                "    </vpn-base-config>\n"
                "  </config>\n"
                "</config-auth>\n"
            )
            self._respond(200, "text/xml", xml.encode("utf-8"))
            return
        self._respond(400, "text/plain", b"unknown config-auth type")

    def _serve_login_form(self):
        """Mock IdP login page — minimal HTML form openconnect-saml's headless
        auto-fill recognises (input[type=email] + input[name=passwd])."""
        action = f"{self.server_owner.url}/+CSCOE+/saml/sp/acs"
        html = f"""<!doctype html>
<html><body>
  <form method="POST" action="{action}">
    <input type="email" name="username" />
    <input type="password" name="passwd" />
    <input type="submit" id="idSIButton9" value="Sign in" />
  </form>
</body></html>"""
        self._respond(200, "text/html", html.encode("utf-8"))

    def _handle_saml_acs(self, body: bytes):
        """Receive the IdP form post (or GET redirect) → set the webvpn cookie."""
        # Parse the body if it's a form post — surface the credentials in the
        # request log so tests can verify the auto-fill plumbed them through.
        if body:
            try:
                form = parse_qs(body.decode("utf-8", errors="replace"))
                self.server_owner.last_credentials = {
                    "username": (form.get("username") or [""])[0],
                    "password": (form.get("passwd") or [""])[0],
                }
            except Exception:
                pass
        # Always succeed; set the SSO token cookie and return a tiny success page.
        self.send_response(200)
        self.send_header("Set-Cookie", f"webvpn={SSO_TOKEN}; Path=/")
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body>SAML auth complete.</body></html>")

    # -- low-level helper -------------------------------------------------

    def _respond(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MockGateway:
    """HTTPS server combining mock gateway + mock SAML IdP on one origin."""

    def __init__(self, host: str = "localhost", verbose: bool = False):
        self.host = host
        self.verbose = verbose
        self.port = _free_port()
        self.url = f"https://{host}:{self.port}"
        self.request_log: list[dict] = []
        self.last_credentials: dict | None = None
        self._cert_path, self._key_path = _generate_self_signed_cert(host)

        _Handler.server_owner = self  # bind the handler back to this instance
        self._server = HTTPServer(("127.0.0.1", self.port), _Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(self._cert_path), keyfile=str(self._key_path))
        self._server.socket = ctx.wrap_socket(self._server.socket, server_side=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- lifecycle --------------------------------------------------------

    def start(self) -> MockGateway:
        self._thread.start()
        # Block until the listener is actually accepting
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("MockGateway didn't start in time")

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
