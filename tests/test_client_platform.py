"""Client platform reported to the Cisco gateway.

The gateway grades a client on two independent strings — the ``<device-id>``
in the ``config-auth`` XML and the AnyConnect ``User-Agent`` — and they use
different vocabularies. These tests pin both, and pin that they agree.
"""

from types import SimpleNamespace

import pytest
from lxml import etree, objectify

from openconnect_saml.authenticator import (
    CLIENT_PLATFORMS,
    _create_auth_finish_request,
    _create_auth_init_request,
    client_user_agent,
    create_http_session,
    default_client_platform,
    resolve_client_platform,
)


@pytest.mark.parametrize(
    ("sys_platform", "expected"),
    [
        ("darwin", "mac-intel"),
        ("win32", "win"),
        ("cygwin", "win"),
        ("linux", "linux-64"),
        ("freebsd14", "linux-64"),
    ],
)
def test_default_client_platform(monkeypatch, sys_platform, expected):
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", sys_platform)
    assert default_client_platform() == expected


def test_windows_is_detected_via_os_name(monkeypatch):
    """``os.name`` is the predicate app.py's Windows branch always used."""
    monkeypatch.setattr("openconnect_saml.authenticator.os.name", "nt")
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "darwin")
    assert default_client_platform() == "win"


def test_apple_silicon_is_still_mac_intel(monkeypatch):
    """Cisco's macOS client is a universal binary: there is no arm64 token."""
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "darwin")
    monkeypatch.setattr("platform.machine", lambda: "arm64")
    assert default_client_platform() == "mac-intel"


@pytest.mark.parametrize("token", sorted(CLIENT_PLATFORMS))
def test_explicit_token_is_honoured(token):
    assert resolve_client_platform(token) == token


@pytest.mark.parametrize("value", [None, "", "   ", "auto", "AUTO"])
def test_blank_and_auto_fall_back_to_detection(monkeypatch, value):
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "darwin")
    assert resolve_client_platform(value) == "mac-intel"


def test_unknown_token_falls_back_instead_of_raising(monkeypatch):
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "linux")
    assert resolve_client_platform("plan9") == "linux-64"


def test_token_is_case_and_space_insensitive():
    assert resolve_client_platform("  MAC-INTEL ") == "mac-intel"


def test_user_agent_uses_the_paired_token():
    assert client_user_agent("4.7.00136", "mac-intel") == "AnyConnect Darwin_i386 4.7.00136"
    assert client_user_agent("4.7.00136", "linux-64") == "AnyConnect Linux_64 4.7.00136"
    assert client_user_agent("4.7.00136", "win") == "AnyConnect Win 4.7.00136"


@pytest.mark.parametrize("token", sorted(CLIENT_PLATFORMS))
def test_user_agent_and_device_id_agree(token):
    """The whole point: a client that claims two different platforms is spoofed."""
    session = create_http_session(None, "4.7.00136", client_os=token)
    ua = session.headers["User-Agent"]
    assert ua == f"AnyConnect {CLIENT_PLATFORMS[token]} {'4.7.00136'}"

    host = SimpleNamespace(name="GroupA")
    init = objectify.fromstring(
        _create_auth_init_request(host, "https://vpn.example.com", "4.7.00136", client_os=token)
    )
    assert init.find("device-id").text == token
    assert CLIENT_PLATFORMS[init.find("device-id").text] in ua


def test_init_request_device_id(monkeypatch):
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "darwin")
    host = SimpleNamespace(name="GroupA")
    tree = etree.fromstring(_create_auth_init_request(host, "https://vpn.example.com", "4.7.00136"))
    assert tree.find("device-id").text == "mac-intel"


def test_finish_request_device_id_keeps_computer_name(monkeypatch):
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "darwin")
    monkeypatch.setattr("openconnect_saml.authenticator.socket.gethostname", lambda: "work-mac")
    auth_info = SimpleNamespace(opaque=objectify.fromstring(b"<opaque is-for='sg'/>"))
    tree = etree.fromstring(
        _create_auth_finish_request(None, auth_info, "MY-SSO-TOKEN", "4.7.00136")
    )
    device = tree.find("device-id")
    assert device.text == "mac-intel"
    assert device.get("computer-name") == "work-mac"


@pytest.mark.parametrize("sys_platform", ["darwin", "win32", "linux"])
def test_client_os_linux_64_restores_legacy_output(monkeypatch, sys_platform):
    """``--client-os linux-64`` must reproduce the old hardcoded behaviour exactly.

    This is the documented rollback: if a gateway DAP rule rejects the real OS,
    forcing linux-64 has to be byte-identical to the pre-change client.
    """
    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", sys_platform)
    monkeypatch.setattr("openconnect_saml.authenticator.socket.gethostname", lambda: "work-mac")
    host = SimpleNamespace(name="GroupA")
    auth_info = SimpleNamespace(opaque=objectify.fromstring(b"<opaque is-for='sg'/>"))

    session = create_http_session(None, "4.7.00136", client_os="linux-64")
    assert session.headers["User-Agent"] == "AnyConnect Linux_64 4.7.00136"

    init = _create_auth_init_request(
        host, "https://vpn.example.com", "4.7.00136", client_os="linux-64"
    )
    assert b"<device-id>linux-64</device-id>" in init

    finish = _create_auth_finish_request(
        None, auth_info, "MY-SSO-TOKEN", "4.7.00136", client_os="linux-64"
    )
    assert b'<device-id computer-name="work-mac">linux-64</device-id>' in finish


def test_authenticator_resolves_platform_once(monkeypatch):
    """The Authenticator pins one token so the UA and both bodies cannot drift."""
    from openconnect_saml.authenticator import Authenticator

    monkeypatch.setattr("openconnect_saml.authenticator.sys.platform", "darwin")
    auth = Authenticator(SimpleNamespace(name="GroupA", vpn_url="https://vpn.example.com"))
    assert auth.client_os == "mac-intel"
    assert auth.session.headers["User-Agent"].startswith("AnyConnect Darwin_i386 ")


def test_cli_exposes_client_os_and_does_not_steal_openconnect_os():
    """``--os`` must keep falling through to the openconnect binary."""
    from openconnect_saml.cli import create_legacy_argparser

    parser = create_legacy_argparser()
    args, unknown = parser.parse_known_args(
        ["--server", "vpn.example.com", "--client-os", "mac-intel", "--os=mac-intel"]
    )
    assert args.client_os == "mac-intel"
    forwarded = list(getattr(args, "openconnect_args", []) or []) + unknown
    assert "--os=mac-intel" in forwarded
    assert not any(a.startswith("--client-os") for a in forwarded)
