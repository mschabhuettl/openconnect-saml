from types import SimpleNamespace

import pytest
from lxml import objectify

from openconnect_saml.authenticator import parse_auth_request_response
from openconnect_saml.browser.chrome import ChromeBrowser
from openconnect_saml.cli import _recover_connect_options_from_remainder, create_argparser


def test_connect_profile_recovers_browser_after_profile_name():
    parser = create_argparser()
    args = parser.parse_args(["connect", "work", "--browser", "chrome", "--", "--passwd-on-stdin"])

    _recover_connect_options_from_remainder(args)

    assert args.profile_name == "work"
    assert args.browser == "chrome"
    assert args.openconnect_args == ["--passwd-on-stdin"]


def test_parse_auth_request_finds_namespaced_sso_fields():
    xml = objectify.fromstring(
        b'''<config-auth type="auth-request" xmlns:c="urn:test">
          <opaque>abc</opaque>
          <auth id="main">
            <title>Login</title>
            <c:sso-v2-login>https://vpn.example.com/+CSCOE+/saml/sp/login</c:sso-v2-login>
            <c:sso-v2-login-final>https://vpn.example.com/+CSCOE+/saml_ac_login.html</c:sso-v2-login-final>
            <c:sso-v2-token-cookie-name>acSamlv2Token</c:sso-v2-token-cookie-name>
          </auth>
        </config-auth>'''
    )

    resp = parse_auth_request_response(xml, response_url="https://vpn.example.com/+CSCOE+/saml_ac_login.html")

    assert resp.login_url == "https://vpn.example.com/+CSCOE+/saml/sp/login"
    assert resp.login_final_url == "https://vpn.example.com/+CSCOE+/saml_ac_login.html"
    assert resp.token_cookie_name == "acSamlv2Token"


def test_parse_auth_request_falls_back_to_form_action_for_newer_duo_flow():
    xml = objectify.fromstring(
        b'''<config-auth type="auth-request">
          <opaque>abc</opaque>
          <auth id="main">
            <title>Duo</title>
            <form action="/+CSCOE+/saml_ac_login.html" method="post" />
          </auth>
        </config-auth>'''
    )

    resp = parse_auth_request_response(xml, response_url="https://vpn.example.com/+CSCOE+/logon.html")

    assert resp.login_url == "https://vpn.example.com/+CSCOE+/saml_ac_login.html"
    assert resp.login_final_url == resp.login_url
    assert resp.token_cookie_name == "webvpn"


class _FakeLocator:
    def __init__(self, visible=False, value=""):
        self.first = self
        self.visible = visible
        self.value = value
        self.filled = []
        self.clicked = 0

    async def is_visible(self, timeout=0):
        return self.visible

    async def input_value(self):
        return self.value

    async def fill(self, value):
        self.value = value
        self.filled.append(value)

    async def click(self):
        self.clicked += 1


class _FakePage:
    def __init__(self):
        self.locators = {
            "input[id=username]": _FakeLocator(visible=True),
            "input[type=submit]": _FakeLocator(visible=True),
        }

    def locator(self, selector):
        return self.locators.get(selector, _FakeLocator())


@pytest.mark.asyncio
async def test_chrome_autofill_supports_id_username_and_clicks_once():
    browser = ChromeBrowser()
    browser._page = _FakePage()
    creds = SimpleNamespace(username="alice", password="", totp="")

    assert await browser._auto_fill(creds) is True
    assert browser._page.locators["input[id=username]"].filled == ["alice"]

    clicked = set()
    assert await browser._try_click_selectors(["input[type=submit]"], clicked) is True
    assert await browser._try_click_selectors(["input[type=submit]"], clicked) is False
    assert browser._page.locators["input[type=submit]"].clicked == 1
