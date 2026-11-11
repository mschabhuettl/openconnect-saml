"""Saved login settings and connection arguments."""

import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import toml

from openconnect_saml import app, config, sessions
from openconnect_saml.cli import create_argparser


def configured():
    return config.Config.from_dict(
        {
            "username_only": True,
            "chrome_channel": "chrome",
            "profiles": {
                "work": {
                    "server": "https://vpn.example.com",
                    "browser": "chrome",
                    "openconnect_args": ["--script", "/usr/local/libexec/example-vpnc-script"],
                }
            },
        }
    )


def test_username_only_roundtrip_and_explicit_profile_override():
    cfg = configured()
    cfg.get_profile("work").username_only = False
    restored = config.Config.from_dict(toml.loads(toml.dumps(cfg.as_dict())))
    assert restored.get_setting("username_only") is True
    assert restored.get_setting("username_only", "work") is False
    assert restored.chrome_channel == "chrome"
    assert restored.get_profile("work").openconnect_args == cfg.get_profile("work").openconnect_args


def test_connection_resolves_saved_arguments_and_records_session(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    cfg = configured()
    options = SimpleNamespace(
        profile_name="work",
        proxy=None,
        ac_version="version",
        openconnect_args=[],
        user=None,
    )
    host = config.HostProfile("vpn.example.com", "", "")
    with patch("openconnect_saml.app.run_openconnect", return_value=0) as run:
        assert app._connect_with_token_refresh(options, cfg, MagicMock(), host) == 0
    assert run.call_args.args[4] == cfg.get_profile("work").openconnect_args
    run.call_args.kwargs["on_pid"](1234)
    recorded = sessions.Session.from_dict(json.loads(sessions.session_file("work").read_text()))
    assert recorded.pid == 1234
    # Adding a command-line option must retain the saved routing script.
    saved = list(cfg.get_profile("work").openconnect_args)
    options.openconnect_args = ["--protocol=anyconnect"]
    with patch("openconnect_saml.app.run_openconnect", return_value=0) as run:
        app._connect_with_token_refresh(options, cfg, MagicMock(), host)
    assert run.call_args.args[4] == [*saved, "--protocol=anyconnect"]
    assert cfg.get_profile("work").openconnect_args == saved


def test_saved_username_and_system_chrome_need_no_repeated_flags():
    cfg = configured()
    cfg.credentials = config.Credentials("remembered-user")
    options = SimpleNamespace(
        profile_name="work",
        user=None,
        server="vpn.example.com",
        use_profile_selector=False,
        usergroup="",
        authgroup="",
        profile_path=None,
        browser=None,
        browser_display_mode="shown",
        proxy=None,
        ac_version="version",
        on_disconnect="",
        no_token_cache=True,
    )
    with (
        patch.object(app, "authenticate_to", AsyncMock()) as auth,
        patch.object(app, "_read_password") as prompt,
    ):
        asyncio.run(app._run(options, cfg))
    prompt.assert_not_called()
    assert auth.call_args.args[2].username == "remembered-user"
    assert auth.call_args.args[2].username_only is True
    assert auth.call_args.kwargs["chrome_channel"] == "chrome"


def test_profile_username_reaches_browser_without_global_credentials():
    cfg = configured()
    profile = cfg.get_profile("work")
    profile.credentials = config.Credentials("profile-user", totp_source="none")
    options = create_argparser().parse_args(["connect", "work"])
    options.no_token_cache = True
    options.server = profile.server
    with (
        patch.object(app, "authenticate_to", AsyncMock()) as login,
        patch.object(app, "_read_password") as prompt,
    ):
        asyncio.run(app._run(options, cfg))
    sent = login.call_args.args[2]
    assert sent.username == "profile-user"
    assert sent.username_only is True
    assert sent.password is None
    prompt.assert_not_called()


@pytest.mark.skipif(os.name == "nt", reason="sudo is POSIX-only")
def test_sudo_prompt_identifies_local_system_password():
    with (
        patch.object(
            app.shutil,
            "which",
            side_effect=lambda name: "/usr/bin/sudo" if name == "sudo" else None,
        ),
        patch.object(app.subprocess, "run") as command,
    ):
        app.run_openconnect(
            MagicMock(session_token="cookie", server_cert_hash="pin"),
            config.HostProfile("vpn.invalid", "", ""),
            None,
            "version",
            [],
        )
    arguments = command.call_args.args[0]
    assert arguments[:2] == ["sudo", "-p"]
    assert "Local system password" in arguments[2]
    assert arguments[3] == "openconnect"
    assert command.call_args.kwargs["input"] == b"cookie"


def test_tui_disconnects_managed_profile_instead_of_terminating_supervisor():
    from openconnect_saml.interactive_tui import InteractiveTUI

    cfg = configured()
    cfg.add_profile("zzz", {"server": "other.invalid"})
    with patch("openconnect_saml.interactive_tui.config.load", return_value=cfg):
        tui = InteractiveTUI()
    child = MagicMock()
    child.poll.return_value = None
    with patch("openconnect_saml.interactive_tui.subprocess.Popen", return_value=child):
        tui._connect()
    tui.cursor = 1
    with patch(
        "openconnect_saml.interactive_tui.subprocess.run",
        return_value=SimpleNamespace(returncode=0),
    ) as stop:
        tui._disconnect()
    assert stop.call_args.args[0][-2:] == ["disconnect", "work"]
    child.terminate.assert_not_called()
