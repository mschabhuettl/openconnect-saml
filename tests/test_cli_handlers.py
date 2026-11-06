"""Tests for the small cli.py command handlers.

Targets the leaf handlers (`_handle_disconnect_command`,
`_handle_sessions_command`, `_handle_run_command`, plus the
missing branches of `_handle_groups_command`) so we exercise the
print/exit-code paths without spinning up the full openconnect
binary or a real session file.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from openconnect_saml import config
from openconnect_saml.cli import (
    _handle_disconnect_command,
    _handle_groups_command,
    _handle_run_command,
    _handle_sessions_command,
)
from openconnect_saml.sessions import Session


def _mk_session(profile="work", server="vpn.example.com", pid=4242):
    return Session(
        profile=profile,
        server=server,
        user="alice",
        pid=pid,
        parent_pid=pid - 1,
        interface="tun0",
        started_at="2026-01-02T03:04:05+00:00",
    )


def _mk_cfg_with_profiles(*names):
    cfg = config.Config()
    for n in names:
        cfg.add_profile(n, {"server": f"{n}.example.com"})
    return cfg


# --------------------------------------------------------- _handle_disconnect_command


class TestDisconnectCommand:
    def test_no_active_sessions(self, capsys):
        args = SimpleNamespace(profile_name=None, all=False)
        with patch("openconnect_saml.sessions.list_active", return_value=[]):
            rc = _handle_disconnect_command(args)
        assert rc == 0
        assert "No active sessions" in capsys.readouterr().out

    def test_disconnect_all_kills_each(self, capsys):
        sessions = [_mk_session("work", pid=10), _mk_session("home", pid=20)]
        args = SimpleNamespace(profile_name=None, all=True)
        with (
            patch("openconnect_saml.sessions.list_active", return_value=sessions),
            patch("openconnect_saml.sessions.kill", return_value=True) as mk,
        ):
            rc = _handle_disconnect_command(args)
        assert rc == 0
        # kill called once per session
        assert mk.call_count == 2
        out = capsys.readouterr().out
        assert "Disconnected 'work'" in out
        assert "Disconnected 'home'" in out

    def test_disconnect_all_returns_1_when_nothing_killed(self, capsys):
        sessions = [_mk_session("work", pid=10)]
        args = SimpleNamespace(profile_name=None, all=True)
        with (
            patch("openconnect_saml.sessions.list_active", return_value=sessions),
            patch("openconnect_saml.sessions.kill", return_value=False),
        ):
            rc = _handle_disconnect_command(args)
        assert rc == 1

    def test_disconnect_all_reports_partial_failure(self):
        with (
            patch(
                "openconnect_saml.sessions.list_active",
                return_value=[_mk_session("work"), _mk_session("home")],
            ),
            patch("openconnect_saml.sessions.kill", side_effect=[True, False]),
        ):
            assert _handle_disconnect_command(SimpleNamespace(profile_name=None, all=True)) == 1

    def test_disconnect_named_profile(self, capsys):
        args = SimpleNamespace(profile_name="work", all=False)
        with patch("openconnect_saml.sessions.kill", return_value=True) as mk:
            rc = _handle_disconnect_command(args)
        assert rc == 0
        mk.assert_called_once_with("work")
        assert "Disconnected 'work'" in capsys.readouterr().out

    def test_failed_disconnect_reports_session_still_active(self, capsys):
        args = SimpleNamespace(profile_name="work", all=False)
        with (
            patch("openconnect_saml.sessions.kill", return_value=False),
            patch("openconnect_saml.sessions.load", return_value=_mk_session("work")),
        ):
            assert _handle_disconnect_command(args) == 1
        output = capsys.readouterr()
        assert "session is still active" in output.err
        assert "No active session" not in output.out
        assert "Did you mean" not in output.out

    def test_disconnect_unknown_profile_suggests_close_match(self, capsys):
        args = SimpleNamespace(profile_name="wrok", all=False)
        with (
            patch("openconnect_saml.sessions.kill", return_value=False),
            patch(
                "openconnect_saml.sessions.list_active",
                return_value=[_mk_session("work")],
            ),
        ):
            rc = _handle_disconnect_command(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "No active session for profile 'wrok'" in out
        assert "Did you mean: work" in out

    def test_disconnect_unknown_profile_no_close_matches(self, capsys):
        args = SimpleNamespace(profile_name="totally-different", all=False)
        with (
            patch("openconnect_saml.sessions.kill", return_value=False),
            patch(
                "openconnect_saml.sessions.list_active",
                return_value=[_mk_session("work")],
            ),
        ):
            rc = _handle_disconnect_command(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "No active session" in out
        assert "Did you mean" not in out


# --------------------------------------------------------- _handle_sessions_command


class TestSessionsCommand:
    def test_list_empty(self, capsys):
        args = SimpleNamespace(sessions_action="list", json=False)
        with patch("openconnect_saml.sessions.list_active", return_value=[]):
            rc = _handle_sessions_command(args)
        assert rc == 0
        assert "No active sessions" in capsys.readouterr().out

    def test_list_text_format(self, capsys):
        sessions = [_mk_session("work", "vpn.example.com", 4242)]
        args = SimpleNamespace(sessions_action="list", json=False)
        with patch("openconnect_saml.sessions.list_active", return_value=sessions):
            rc = _handle_sessions_command(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Profile" in out
        assert "work" in out
        assert "4242" in out
        assert "vpn.example.com" in out

    def test_list_json_format(self, capsys):
        sessions = [_mk_session("work", "vpn.example.com", 4242)]
        args = SimpleNamespace(sessions_action="list", json=True)
        with patch("openconnect_saml.sessions.list_active", return_value=sessions):
            rc = _handle_sessions_command(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert data[0]["profile"] == "work"
        assert data[0]["pid"] == 4242

    def test_default_action_is_list(self, capsys):
        args = SimpleNamespace(sessions_action=None, json=False)
        with patch("openconnect_saml.sessions.list_active", return_value=[]):
            rc = _handle_sessions_command(args)
        assert rc == 0

    def test_unknown_action(self, capsys):
        args = SimpleNamespace(sessions_action="warp-drive", json=False)
        with patch("openconnect_saml.sessions.list_active", return_value=[]):
            rc = _handle_sessions_command(args)
        assert rc == 1
        assert "Unknown sessions action" in capsys.readouterr().out


# --------------------------------------------------------- _handle_run_command


class TestRunCommand:
    def test_no_command_returns_error(self, capsys):
        args = SimpleNamespace(profile_name="work", command_argv=[], run_wait=15)
        rc = _handle_run_command(args)
        assert rc == 1
        assert "no command given" in capsys.readouterr().err

    def test_only_dashdash_after_profile(self, capsys):
        args = SimpleNamespace(profile_name="work", command_argv=["--"], run_wait=15)
        rc = _handle_run_command(args)
        assert rc == 1
        assert "no command given after '--'" in capsys.readouterr().err

    def test_bringup_failure_short_circuits(self, capsys):
        args = SimpleNamespace(profile_name="work", command_argv=["echo", "hi"], run_wait=15)
        bringup = MagicMock(returncode=42)
        with patch("subprocess.run", return_value=bringup) as run:
            rc = _handle_run_command(args)
        assert rc == 42
        # Only the bring-up was invoked; the user command never ran.
        assert run.call_count == 1
        err = capsys.readouterr().err
        assert "could not bring up profile 'work'" in err

    def test_happy_path_disconnects_after_command(self, capsys):
        args = SimpleNamespace(profile_name="work", command_argv=["--", "echo", "hi"], run_wait=15)
        bringup = MagicMock(returncode=0)
        usercmd = MagicMock(returncode=7)
        with (
            patch("subprocess.run", side_effect=[bringup, usercmd]) as run,
            patch("openconnect_saml.sessions.kill", return_value=True) as mk,
            patch("signal.signal"),
        ):
            rc = _handle_run_command(args)
        assert rc == 7
        # Bring-up + user command, leading "--" stripped from user command.
        assert run.call_args_list[1].args[0] == ["echo", "hi"]
        mk.assert_called_once_with("work")

    def test_kill_failure_is_warned_but_not_fatal(self, capsys):
        args = SimpleNamespace(profile_name="work", command_argv=["true"], run_wait=15)
        bringup = MagicMock(returncode=0)
        usercmd = MagicMock(returncode=0)
        with (
            patch("subprocess.run", side_effect=[bringup, usercmd]),
            patch("openconnect_saml.sessions.kill", side_effect=RuntimeError("boom")),
            patch("signal.signal"),
        ):
            rc = _handle_run_command(args)
        # User command succeeded; kill failure is just a warning.
        assert rc == 0
        assert "could not disconnect 'work'" in capsys.readouterr().err


# --------------------------------------------------------- _handle_groups_command (gaps)


class TestGroupsConnect:
    def test_connect_unknown_group(self, capsys):
        cfg = _mk_cfg_with_profiles("eu")
        args = SimpleNamespace(groups_action="connect", group_name="ghost")
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(args)
        assert rc == 1
        assert "group 'ghost' not found" in capsys.readouterr().err

    def test_connect_empty_group(self, capsys):
        cfg = _mk_cfg_with_profiles("eu")
        cfg.profile_groups = {"empty": []}
        args = SimpleNamespace(groups_action="connect", group_name="empty")
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(args)
        assert rc == 1
        assert "no members" in capsys.readouterr().err

    def test_connect_runs_each_member(self, capsys):
        cfg = _mk_cfg_with_profiles("eu", "us")
        cfg.profile_groups = {"work": ["eu", "us"]}
        args = SimpleNamespace(groups_action="connect", group_name="work")
        good = MagicMock(returncode=0)
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("subprocess.run", return_value=good) as run,
        ):
            rc = _handle_groups_command(args)
        assert rc == 0
        assert run.call_count == 2
        out = capsys.readouterr().out
        assert "Connecting 'eu'" in out
        assert "Connecting 'us'" in out

    def test_connect_propagates_failure_exit_code(self, capsys):
        cfg = _mk_cfg_with_profiles("eu", "us")
        cfg.profile_groups = {"work": ["eu", "us"]}
        args = SimpleNamespace(groups_action="connect", group_name="work")
        # First profile fails, second succeeds — handler returns the
        # first non-zero exit code observed.
        results = [MagicMock(returncode=3), MagicMock(returncode=0)]
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("subprocess.run", side_effect=results),
        ):
            rc = _handle_groups_command(args)
        assert rc == 3
        assert "'eu' failed (exit 3)" in capsys.readouterr().out


class TestGroupsDisconnect:
    def test_disconnect_unknown_group(self, capsys):
        cfg = _mk_cfg_with_profiles("eu")
        args = SimpleNamespace(groups_action="disconnect", group_name="ghost")
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(args)
        assert rc == 1
        assert "group 'ghost' not found" in capsys.readouterr().err

    def test_disconnect_no_active_in_group(self, capsys):
        cfg = _mk_cfg_with_profiles("eu", "us")
        cfg.profile_groups = {"work": ["eu", "us"]}
        args = SimpleNamespace(groups_action="disconnect", group_name="work")
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.sessions.list_active", return_value=[]),
        ):
            rc = _handle_groups_command(args)
        assert rc == 1
        assert "No active sessions in group 'work'" in capsys.readouterr().out

    def test_disconnect_kills_active_members(self, capsys):
        cfg = _mk_cfg_with_profiles("eu", "us", "asia")
        cfg.profile_groups = {"work": ["eu", "us", "asia"]}
        args = SimpleNamespace(groups_action="disconnect", group_name="work")
        # Only "eu" and "us" are active; asia is in the group but not running.
        active = [_mk_session("eu"), _mk_session("us")]
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.sessions.list_active", return_value=active),
            patch("openconnect_saml.sessions.kill", return_value=True) as mk,
        ):
            rc = _handle_groups_command(args)
        assert rc == 0
        # asia is in the group but never killed since it isn't active
        kill_targets = {c.args[0] for c in mk.call_args_list}
        assert kill_targets == {"eu", "us"}


class TestGroupsUnknownAction:
    def test_unknown_action_exits_1(self, capsys):
        cfg = config.Config()
        args = SimpleNamespace(groups_action="warp-drive")
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(args)
        assert rc == 1
        assert "Unknown groups action" in capsys.readouterr().out


# pytest is needed for parametrize markers if any; keep the import live.
_ = pytest
