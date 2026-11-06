"""Session reuse and refresh without accessing the user's real keyring."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import keyring.errors
import pytest

from openconnect_saml import app, config, token_cache
from openconnect_saml.authenticator import AuthCompleteResponse


@pytest.fixture
def vault(monkeypatch):
    values = {}
    monkeypatch.setattr(token_cache.keyring, "get_password", lambda s, k: values.get((s, k)))
    monkeypatch.setattr(
        token_cache.keyring, "set_password", lambda s, k, v: values.__setitem__((s, k), v)
    )
    monkeypatch.setattr(
        token_cache.keyring, "delete_password", lambda s, k: values.pop((s, k), None)
    )
    return values


def args(**overrides):
    values = dict(
        user=None,
        server="vpn.example.com",
        usergroup="",
        authgroup="",
        use_profile_selector=False,
        profile_path=None,
        browser="chrome",
        proxy=None,
        ac_version="4.7.00136",
        on_disconnect="",
        on_connect="",
        openconnect_args=[],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def host(address="vpn.example.com"):
    return config.HostProfile(address, "", "")


def response(cookie="new-cookie"):
    return AuthCompleteResponse("success", "", cookie, "sha256:abc")


def test_key_isolates_endpoint_account_group_and_profile():
    host = config.HostProfile("vpn.example.com", "", "")
    key = token_cache.cache_key(host, "alice", "work")
    assert key != token_cache.cache_key(host, "bob", "work")
    assert key != token_cache.cache_key(host, "alice", "other")
    assert key != token_cache.cache_key(
        config.HostProfile("other.example.com", "", ""), "alice", "work"
    )
    assert key != token_cache.cache_key(
        config.HostProfile("vpn.example.com", "group", ""), "alice", "work"
    )
    assert key != token_cache.cache_key(
        config.HostProfile("vpn.example.com", "", "group"), "alice", "work"
    )


def test_roundtrip_and_delete(vault):
    token_cache.save("key", response(), host())
    restored = token_cache.load("key")
    assert restored.response.session_token == "new-cookie"
    assert restored.response.server_cert_hash == "sha256:abc"
    assert (token_cache.SERVICE, "key") in vault
    token_cache.delete("key")
    assert token_cache.load("key") is None


@pytest.mark.parametrize(
    "value", ["bad-json", "null", "[]", "{}", '{"cookie": 42, "fingerprint": "a"}']
)
def test_corrupt_cache_is_a_miss(vault, value):
    vault[token_cache.SERVICE, "key"] = value
    assert token_cache.load("key") is None


def test_unavailable_keyring_does_not_prevent_login(monkeypatch):
    def unavailable(*a):
        raise keyring.errors.NoKeyringError("unavailable")

    for method in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(token_cache.keyring, method, unavailable)
    assert token_cache.load("key") is None
    token_cache.save("key", response(), host())
    token_cache.delete("key")


@pytest.mark.parametrize(
    "detach",
    [
        False,
        pytest.param(
            True,
            marks=pytest.mark.skipif(
                os.name != "posix", reason="Native background reuse is POSIX-only"
            ),
        ),
    ],
)
def test_cached_session_skips_browser_and_credential_prompts(vault, detach):
    options = args(user="alice", detach=detach)
    cfg = config.Config()
    key = token_cache.cache_key(config.HostProfile(options.server, "", ""), "alice")
    token_cache.save(key, response("cached-cookie"), host())
    with (
        patch.object(app, "authenticate_to", new_callable=AsyncMock) as auth,
        patch.object(app, "_read_password") as prompt,
    ):
        result, _ = asyncio.run(app._run(options, cfg))
    assert result.session_token == "cached-cookie"
    assert options._using_cached_token
    auth.assert_not_called()
    prompt.assert_not_called()


@pytest.mark.parametrize(
    "override",
    [
        {"no_token_cache": True},
        {"forget_token": True},
        {"authenticate": "json"},
        {"kill_switch": True},
    ],
)
def test_fresh_login_options_bypass_cache(vault, override):
    options = args(**override)
    cfg = config.Config()
    key = token_cache.cache_key(config.HostProfile(options.server, "", ""))
    token_cache.save(key, response("old-cookie"), host())
    with patch.object(app, "authenticate_to", AsyncMock(return_value=response())) as auth:
        result, _ = asyncio.run(app._run(options, cfg))
    assert result.session_token == "new-cookie"
    auth.assert_awaited_once()
    assert not options._using_cached_token
    expected = "old-cookie" if override.get("no_token_cache") else "new-cookie"
    assert token_cache.load(key).response.session_token == expected


def test_username_only_does_not_read_saved_passwords_or_totp(vault):
    options = args(user="alice", username_only=True)
    cfg = config.Config(credentials={"username": "bob"})
    with (
        patch.object(app, "authenticate_to", AsyncMock(return_value=response())) as auth,
        patch.object(app, "_read_password") as prompt,
    ):
        asyncio.run(app._run(options, cfg))
    sent = auth.call_args.args[2]
    assert sent.username == "alice"
    assert sent.password is None
    assert sent.totp is None
    assert cfg.credentials.username == "alice"
    prompt.assert_not_called()


@pytest.mark.parametrize(
    "rc, cached, calls", [(0, True, 1), (1, True, 1), (20, True, 1), (2, False, 1), (2, True, 2)]
)
def test_only_rejected_cached_cookie_triggers_refresh(vault, rc, cached, calls):
    options = args(_using_cached_token=cached, _token_cache_key="key")
    cfg = config.Config()
    old = response("old")
    fresh = response("fresh")
    host = config.HostProfile(options.server, "", "")
    token_cache.save("key", old, host)
    with (
        patch.object(app, "run_openconnect", side_effect=[rc, 0]) as connect,
        patch.object(app, "_run", AsyncMock(return_value=(fresh, host))) as auth,
        patch.object(app.config, "save"),
    ):
        result = app._connect_with_token_refresh(options, cfg, old, host, no_sudo=True)
    assert connect.call_count == calls
    if calls == 2:
        assert result == 0
        auth.assert_awaited_once_with(options, cfg, force_auth=True, profile_override=None)
        assert token_cache.load("key") is None
        assert connect.call_args.args[0] is fresh
        assert connect.call_args.kwargs["no_sudo"] is True
    else:
        assert result == rc
        auth.assert_not_called()


def test_refresh_failure_does_not_retry_forever(vault):
    options = args(_using_cached_token=True, _token_cache_key="key")
    with (
        patch.object(app, "run_openconnect", return_value=2) as connect,
        patch.object(app, "_run", AsyncMock(side_effect=RuntimeError("failed"))),
    ):
        assert (
            app._connect_with_token_refresh(
                options, config.Config(), response(), config.HostProfile(options.server, "", "")
            )
            == 2
        )
    connect.assert_called_once()


def test_new_settings_config_roundtrip():
    cfg = config.Config.from_dict(
        {"token_cache": False, "username_only": True, "chrome_user_data_dir": "~/vpn-chrome"}
    )
    assert not cfg.token_cache
    assert cfg.username_only
    assert cfg.chrome_user_data_dir == "~/vpn-chrome"
    assert json.loads(json.dumps(cfg.as_dict()))["chrome_user_data_dir"] == "~/vpn-chrome"


def test_fresh_cookie_rejection_is_not_retried_and_is_removed(vault):
    options = args(_using_cached_token=True, _token_cache_key="key")
    cfg = config.Config()
    host = config.HostProfile(options.server, "", "")
    token_cache.save("key", response("old"), host)

    async def fresh_login(*a, **kw):
        token_cache.save("key", response("fresh-but-rejected"), host)
        options._using_cached_token = False
        return response("fresh-but-rejected"), host

    with (
        patch.object(app, "run_openconnect", return_value=2) as connect,
        patch.object(app, "_run", side_effect=fresh_login) as auth,
        patch.object(app.config, "save"),
    ):
        assert app._connect_with_token_refresh(options, cfg, response("old"), host) == 2
    assert connect.call_count == 2
    auth.assert_called_once()
    assert token_cache.load("key") is None


def test_redirected_gateway_is_reused_but_refresh_starts_at_requested_gateway(vault):
    options = args(user="alice", username_only=True)
    cfg = config.Config()
    seen = []

    async def login(target, *a, **kw):
        seen.append(target.vpn_url)
        target.address = "https://node.example.com/group"
        return response()

    with patch.object(app, "authenticate_to", AsyncMock(side_effect=login)) as authenticate:
        asyncio.run(app._run(options, cfg))
        cached, target = asyncio.run(app._run(options, cfg))
        assert target.vpn_url == "https://node.example.com/group"
        assert cfg.default_profile.vpn_url == "https://vpn.example.com"
        assert authenticate.await_count == 1
        with (
            patch.object(app, "run_openconnect", side_effect=[2, 0]) as connect,
            patch.object(app.config, "save"),
        ):
            assert app._connect_with_token_refresh(options, cfg, cached, target) == 0
    assert seen == ["https://vpn.example.com", "https://vpn.example.com"]
    assert connect.call_args.args[1].vpn_url == "https://node.example.com/group"


def test_cached_gateway_path_is_not_overridden_by_original_login_group(vault):
    options = args(user="alice", username_only=True, usergroup="/requested")
    requested = config.HostProfile(options.server, options.usergroup, "")
    key = token_cache.cache_key(requested, "alice")
    final = "https://node.example.com/final"
    token_cache.save(key, response("cached-cookie"), host(final))
    with patch.object(app, "authenticate_to", AsyncMock()) as login:
        cached, target = asyncio.run(app._run(options, config.Config()))
    assert cached.session_token == "cached-cookie"
    assert target.vpn_url == final
    assert options._auth_profile.vpn_url == requested.vpn_url
    login.assert_not_called()


def test_disabled_cache_does_not_delete_existing_entry_on_cookie_rejection(vault):
    options = args(no_token_cache=True)
    cfg = config.Config()
    key = token_cache.cache_key(host())
    token_cache.save(key, response("keep-me"), host())
    with (
        patch.object(app, "authenticate_to", AsyncMock(return_value=response())),
        patch.object(app, "run_openconnect", return_value=2),
    ):
        auth, target = asyncio.run(app._run(options, cfg))
        assert app._connect_with_token_refresh(options, cfg, auth, target) == 2
    assert token_cache.load(key).response.session_token == "keep-me"


@pytest.mark.parametrize("username", ["alice", None])
def test_username_only_never_accesses_or_saves_application_passwords(vault, username):
    from unittest.mock import PropertyMock

    cfg = config.Config(
        credentials={"username": username} if username else None, username_only=True
    )
    with (
        patch.object(config.Credentials, "password", new_callable=PropertyMock) as password,
        patch.object(config.Credentials, "totp", new_callable=PropertyMock) as totp,
        patch.object(config.Credentials, "save") as save,
        patch.object(app, "authenticate_to", AsyncMock(return_value=response())) as auth,
        patch.object(app, "_read_password") as prompt,
    ):
        asyncio.run(app._run(args(), cfg))
    password.assert_not_called()
    totp.assert_not_called()
    save.assert_not_called()
    prompt.assert_not_called()
    assert auth.call_args.args[2].username == username
    assert auth.call_args.args[2].username_only


def test_user_alone_still_prompts_for_password_before_browser(vault):
    events = []

    def prompt(*a, **kw):
        events.append("password prompt")
        return "secret"

    async def login(*a, **kw):
        events.append("browser")
        return response()

    with (
        patch.object(app, "_read_password", side_effect=prompt),
        patch.object(app, "authenticate_to", side_effect=login),
    ):
        asyncio.run(app._run(args(user="alice", no_totp=True), config.Config()))
    assert events == ["password prompt", "browser"]
