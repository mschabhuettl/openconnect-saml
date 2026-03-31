import sys

import attr
import pytest

try:
    from openconnect_saml.browser import Browser

    HAS_GUI = True
except (ImportError, OSError):
    HAS_GUI = False
    Browser = None  # type: ignore

from openconnect_saml.config import DisplayMode

pytestmark = pytest.mark.skipif(not HAS_GUI, reason="PyQt6/GUI not available")


@pytest.mark.asyncio
async def test_browser_context_manager_should_work_in_empty_context_manager():
    async with Browser() as _:
        pass


@pytest.mark.xfail(
    sys.platform in ["darwin", "win32"],
    reason="https://github.com/vlaci/openconnect-saml/issues/23",
)
@pytest.mark.asyncio
async def test_browser_reports_loaded_url(httpserver):
    async with Browser(display_mode=DisplayMode.HIDDEN) as browser:
        auth_url = httpserver.url_for("/authenticate")

        await browser.authenticate_at(auth_url, credentials=None)

        assert browser.url is None
        await browser.page_loaded()
        assert browser.url == auth_url


@pytest.mark.xfail(
    sys.platform in ["darwin", "win32"],
    reason="https://github.com/vlaci/openconnect-saml/issues/23",
)
@pytest.mark.asyncio
async def test_browser_cookies_accessible(httpserver):
    async with Browser(display_mode=DisplayMode.HIDDEN) as browser:
        httpserver.expect_request("/authenticate").respond_with_data(
            "<html><body>Hello</body></html>",
            headers={"Set-Cookie": "cookie-name=cookie-value"},
        )
        auth_url = httpserver.url_for("/authenticate")
        cred = Credentials("username", "password")

        await browser.authenticate_at(auth_url, cred)
        await browser.page_loaded()
        assert browser.cookies.get("cookie-name") == "cookie-value"


@attr.s
class Credentials:
    username = attr.ib()
    password = attr.ib()
