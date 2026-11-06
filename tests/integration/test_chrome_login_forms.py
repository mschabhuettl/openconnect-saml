"""Exercise first-login autofill in a real, temporary headless Chrome context."""

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("playwright.async_api")

from openconnect_saml.browser import Terminated
from openconnect_saml.browser.chrome import ChromeBrowser

_CHROME = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
if not _CHROME:
    _mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    _CHROME = str(_mac_chrome) if _mac_chrome.is_file() else None

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _CHROME, reason="A system Chrome executable is required"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_chrome_launch_does_not_disable_its_sandbox(tmp_path, persistent):
    async with ChromeBrowser(
        headless=True,
        executable_path=_CHROME,
        user_data_dir=str(tmp_path / "chrome") if persistent else None,
    ) as browser:
        await browser._page.goto("chrome://version/")
        command = await browser._page.locator("#command_line").inner_text()
        assert "--no-sandbox" not in command


@pytest.mark.asyncio
@pytest.mark.parametrize("placement", ["page", "frame", "popup", "label"])
async def test_shibboleth_username_fills_visible_login_field_without_touching_other_tabs(
    httpserver, placement
):
    form = """<!doctype html><html><body>
        <input type="hidden" name="j_username" value="hidden-sentinel">
        <input type="text" name="j_username" id="login-id" autocomplete="off">
        <input type="password" id="password" value="manual-password">
        <script>
        document.getElementById('login-id').addEventListener('input', event => {
            if (event.target.value === 'test-user') {
                document.cookie = 'test_sso=fresh; Path=/';
            }
        });
        </script>
        </body></html>"""
    if placement == "label":
        form = form.replace(
            'type="text" name="j_username" id="login-id" autocomplete="off"',
            'type="text" name="custom-account" id="login-id" placeholder="Enter your NetID"',
        )
    httpserver.expect_request("/form").respond_with_data(form, content_type="text/html")
    if placement in ("page", "label"):
        login_html = form
    elif placement == "frame":
        login_html = '<html><body><iframe src="/form"></iframe></body></html>'
    else:
        login_html = '<html><body><script>window.open("/form", "login");</script></body></html>'
    httpserver.expect_request("/login").respond_with_data(login_html, content_type="text/html")
    httpserver.expect_request("/done").respond_with_data("done", content_type="text/html")
    credentials = SimpleNamespace(
        username="test-user", password=None, totp=None, username_only=True
    )
    async with ChromeBrowser(headless=True, executable_path=_CHROME, timeout=5_000) as browser:
        unrelated = await browser._context.new_page()
        await unrelated.set_content('<input name="j_username">')
        cookies = await asyncio.wait_for(
            browser.authenticate_at(
                httpserver.url_for("/login"),
                credentials=credentials,
                final_url=httpserver.url_for("/done"),
                token_cookie_name="test_sso",
            ),
            timeout=20,
        )
        assert cookies["test_sso"] == "fresh"
        target = browser._page.frames[-1] if placement == "frame" else browser._page
        assert await target.locator("#login-id").input_value() == "test-user"
        assert await target.locator("input[type=hidden]").input_value() == "hidden-sentinel"
        assert await target.locator("#password").input_value() == "manual-password"
        assert await unrelated.locator("input").input_value() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("completed", [False, True])
async def test_closing_login_window_uses_completed_sso_before_reporting_cancellation(
    httpserver, tmp_path, persistent, completed
):
    httpserver.expect_request("/login").respond_with_data(
        "<html>Login</html>", content_type="text/html"
    )
    httpserver.expect_request("/complete").respond_with_data(
        "<html>Login complete</html>",
        content_type="text/html",
        headers={"Set-Cookie": "test_sso=fresh; HttpOnly; Path=/"},
    )
    entered, resume = asyncio.Event(), asyncio.Event()

    async def pause_form_loop():
        entered.set()
        await resume.wait()

    async with ChromeBrowser(
        headless=True,
        executable_path=_CHROME,
        timeout=5_000,
        user_data_dir=str(tmp_path / "chrome") if persistent else None,
    ) as browser:
        browser._detect_mfa_challenge = pause_form_loop
        task = asyncio.create_task(
            browser.authenticate_at(
                httpserver.url_for("/login"),
                final_url=httpserver.url_for("/complete"),
                token_cookie_name="test_sso",
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            if completed:
                await browser._page.goto(httpserver.url_for("/complete"))
            await browser._page.close()
            resume.set()
            if completed:
                cookies = await asyncio.wait_for(task, timeout=10)
                assert cookies["test_sso"] == "fresh"
            else:
                with pytest.raises(Terminated):
                    await asyncio.wait_for(task, timeout=10)
        finally:
            resume.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
