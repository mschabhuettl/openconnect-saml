import socket
import ssl

import attr
import requests
import requests.adapters
import structlog
from lxml import etree, objectify

from openconnect_saml.saml_authenticator import authenticate_in_browser

logger = structlog.get_logger()


class Authenticator:
    def __init__(
        self,
        host,
        proxy=None,
        credentials=None,
        version=None,
        ssl_legacy=False,
        timeout=30,
        window_width=800,
        window_height=600,
    ):
        self.host = host
        self.proxy = proxy
        self.credentials = credentials
        self.version = version
        self.timeout = timeout
        self.ssl_legacy = ssl_legacy
        self.window_width = window_width
        self.window_height = window_height
        self.session = create_http_session(proxy, version, ssl_legacy=ssl_legacy)

    async def authenticate(self, display_mode):
        self._detect_authentication_target_url()

        response = self._start_authentication()

        # Handle client-cert-request by retrying without cert (#164)
        if isinstance(response, CertRequestResponse):
            response = self._start_authentication(no_cert=True)

        if not isinstance(response, AuthRequestResponse):
            extra = {}
            if isinstance(response, UnexpectedResponse):
                extra["response_type"] = response.response_type
                extra["raw_preview"] = response.raw_content[:500].decode("utf-8", errors="replace")
            logger.error(
                "Could not start authentication. Invalid response type in current state. "
                "If this happens after 2FA, your server may use an unsupported auth flow (#121)",
                response=response,
                **extra,
            )
            raise AuthenticationError(response)

        if response.auth_error:
            logger.error(
                "Could not start authentication. Response contains error",
                error=response.auth_error,
                response=response,
            )
            raise AuthenticationError(response)

        auth_request_response = response

        sso_token = await self._authenticate_in_browser(auth_request_response, display_mode)

        response = self._complete_authentication(auth_request_response, sso_token)
        if not isinstance(response, AuthCompleteResponse):
            extra = {}
            if isinstance(response, UnexpectedResponse):
                extra["response_type"] = response.response_type
                extra["raw_preview"] = response.raw_content[:500].decode("utf-8", errors="replace")
            logger.error(
                "Could not finish authentication. Invalid response type in current state. "
                "If this happens after 2FA, your server may use an unsupported auth flow (#121)",
                response=response,
                **extra,
            )
            raise AuthenticationError(response)

        return response

    def _detect_authentication_target_url(self):
        # Follow possible redirects in a GET request
        # Authentication will occur using a POST request on the final URL
        response = self.session.get(self.host.vpn_url, timeout=self.timeout)
        response.raise_for_status()
        self.host.address = response.url
        logger.debug("Auth target url", url=self.host.vpn_url)

    def _start_authentication(self, no_cert=False):
        request = _create_auth_init_request(self.host, self.host.vpn_url, self.version, no_cert)
        logger.debug("Sending auth init request", content=request)
        response = self.session.post(self.host.vpn_url, request, timeout=self.timeout)
        logger.debug("Auth init response received", content=response.content)
        return parse_response(response)

    async def _authenticate_in_browser(self, auth_request_response, display_mode):
        return await authenticate_in_browser(
            self.proxy,
            auth_request_response,
            self.credentials,
            display_mode,
            window_width=self.window_width,
            window_height=self.window_height,
        )

    def _complete_authentication(self, auth_request_response, sso_token):
        request = _create_auth_finish_request(
            self.host, auth_request_response, sso_token, self.version
        )
        logger.debug("Sending auth finish request", content=request)
        response = self.session.post(self.host.vpn_url, request, timeout=self.timeout)
        logger.debug("Auth finish response received", content=response.content)
        return parse_response(response)


class AuthenticationError(Exception):
    pass


class AuthResponseError(AuthenticationError):
    pass


class SSLLegacyAdapter(requests.adapters.HTTPAdapter):
    """HTTP adapter that enables legacy SSL renegotiation (#81).

    Some older VPN appliances require unsafe legacy renegotiation.
    This adapter creates an SSL context with ``OP_LEGACY_SERVER_CONNECT``
    so that ``requests`` can talk to those servers.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT  # type: ignore[attr-defined]
        except AttributeError:
            # OP_LEGACY_SERVER_CONNECT not available on older Python/OpenSSL
            logger.warning("ssl.OP_LEGACY_SERVER_CONNECT not available, skipping")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def create_http_session(proxy, version, ssl_legacy=False):
    session = requests.Session()
    session.proxies = {"http": proxy, "https": proxy}
    session.headers.update(
        {
            "User-Agent": f"AnyConnect Linux_64 {version}",
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "X-Transcend-Version": "1",
            "X-Aggregate-Auth": "1",
            "X-Support-HTTP-Auth": "true",
            "Content-Type": "application/x-www-form-urlencoded",
            # I know, it is invalid but that's what Anyconnect sends
        }
    )
    if ssl_legacy:
        logger.info("Enabling SSL legacy renegotiation support")
        adapter = SSLLegacyAdapter()
        session.mount("https://", adapter)
    return session


E = objectify.ElementMaker(annotate=False)


def _create_auth_init_request(host, url, version, no_cert=False):
    ConfigAuth = getattr(E, "config-auth")
    Version = E.version
    DeviceId = getattr(E, "device-id")
    GroupSelect = getattr(E, "group-select")
    GroupAccess = getattr(E, "group-access")
    Capabilities = E.capabilities
    AuthMethod = getattr(E, "auth-method")
    ClientCertFail = getattr(E, "client-cert-fail")

    root = ConfigAuth(
        {"client": "vpn", "type": "init", "aggregate-auth-version": "2"},
        Version({"who": "vpn"}, version),
        DeviceId("linux-64"),
        GroupSelect(host.name),
        GroupAccess(url),
        Capabilities(AuthMethod("single-sign-on-v2")),
    )
    if no_cert:
        root.append(ClientCertFail())

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")


def _make_safe_parser(recover=False):
    """Create an XML parser with XXE protections."""
    return objectify.makeparser(
        resolve_entities=False,
        no_network=True,
        recover=recover,
    )


def parse_response(resp):
    resp.raise_for_status()
    try:
        xml = objectify.fromstring(resp.content, parser=_make_safe_parser())
    except etree.XMLSyntaxError:
        # Fallback: use recovery parser for malformed XML (e.g. <br> tags) (#171)
        xml = objectify.fromstring(resp.content, parser=_make_safe_parser(recover=True))
    t = xml.get("type")
    if t == "auth-request":
        return parse_auth_request_response(xml)
    elif t == "complete":
        return parse_auth_complete_response(xml)
    else:
        # #121: Better error for unexpected response types after 2FA
        raw_preview = resp.content[:500].decode("utf-8", errors="replace")
        logger.error(
            "Unexpected response type from VPN server",
            response_type=t,
            raw_preview=raw_preview,
        )
        return UnexpectedResponse(response_type=t, raw_content=resp.content)


def parse_auth_request_response(xml):
    # Handle client-cert-request responses (#164)
    if hasattr(xml, "client-cert-request"):
        logger.info("client-cert-request received")
        return CertRequestResponse()

    # Defensive check: ensure auth element exists (#5)
    if not hasattr(xml, "auth"):
        raise AuthResponseError("Response missing 'auth' element")

    if xml.auth.get("id") != "main":
        raise AuthResponseError(
            f"Expected auth id 'main', got '{xml.auth.get('id')}'"
        )

    try:
        resp = AuthRequestResponse(
            auth_id=xml.auth.get("id"),
            auth_title=getattr(xml.auth, "title", ""),
            auth_message=getattr(xml.auth, "message", ""),  # #161/#175: defensive getattr
            auth_error=getattr(xml.auth, "error", ""),
            opaque=xml.opaque,
            login_url=xml.auth["sso-v2-login"],
            login_final_url=xml.auth["sso-v2-login-final"],
            token_cookie_name=xml.auth["sso-v2-token-cookie-name"],
        )
    except AttributeError as exc:
        raise AuthResponseError(exc) from exc

    logger.info(
        "Response received",
        id=resp.auth_id,
        title=resp.auth_title,
        message=resp.auth_message,
    )
    return resp


@attr.s
class AuthRequestResponse:
    auth_id = attr.ib(converter=str)
    auth_title = attr.ib(converter=str)
    auth_message = attr.ib(converter=str)
    auth_error = attr.ib(converter=str)
    login_url = attr.ib(converter=str)
    login_final_url = attr.ib(converter=str)
    token_cookie_name = attr.ib(converter=str)
    opaque = attr.ib()


@attr.s
class CertRequestResponse:
    """Returned when server requests a client certificate."""

    pass


@attr.s
class UnexpectedResponse:
    """Returned when the server sends an unrecognised response type (#121)."""

    response_type = attr.ib(default=None)
    raw_content = attr.ib(default=b"", repr=False)


def parse_auth_complete_response(xml):
    if not hasattr(xml, "auth"):
        raise AuthResponseError("Response missing 'auth' element")
    if xml.auth.get("id") != "success":
        raise AuthResponseError(
            f"Expected auth id 'success', got '{xml.auth.get('id')}'"
        )

    # #175: Some servers use banner instead of message
    if hasattr(xml.auth, "banner") and xml.auth.banner.text:
        auth_message = xml.auth.banner.text
    else:
        auth_message = getattr(xml.auth, "message", "")

    resp = AuthCompleteResponse(
        auth_id=xml.auth.get("id"),
        auth_message=auth_message,
        session_token=xml["session-token"],
        server_cert_hash=xml.config["vpn-base-config"]["server-cert-hash"],
    )
    logger.info("Response received", id=resp.auth_id, message=resp.auth_message)
    return resp


@attr.s
class AuthCompleteResponse:
    auth_id = attr.ib(converter=str)
    auth_message = attr.ib(converter=str)
    session_token = attr.ib(converter=str)
    server_cert_hash = attr.ib(converter=str)


def _create_auth_finish_request(host, auth_info, sso_token, version):
    hostname = socket.gethostname()

    ConfigAuth = getattr(E, "config-auth")
    Version = E.version
    DeviceId = getattr(E, "device-id")
    SessionToken = getattr(E, "session-token")
    SessionId = getattr(E, "session-id")
    Auth = E.auth
    SsoToken = getattr(E, "sso-token")

    root = ConfigAuth(
        {"client": "vpn", "type": "auth-reply", "aggregate-auth-version": "2"},
        Version({"who": "vpn"}, version),
        DeviceId({"computer-name": hostname}, "linux-64"),
        SessionToken(),
        SessionId(),
        auth_info.opaque,
        Auth(SsoToken(sso_token)),
    )
    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
