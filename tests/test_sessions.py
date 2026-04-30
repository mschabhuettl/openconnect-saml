"""Tests for the multi-session tracking module."""

from __future__ import annotations

import json
import os

import pytest

from openconnect_saml import sessions


@pytest.fixture
def tmp_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    yield tmp_path


def _make(profile="work", server="vpn.example.com", **kw):
    return sessions.Session(profile=profile, server=server, **kw)


class TestSessionFile:
    def test_safe_name_basic(self):
        assert sessions._safe_name("work") == "work"

    def test_safe_name_strips_funky(self):
        assert sessions._safe_name("foo/bar baz") == "foo_bar_baz"

    def test_safe_name_empty_falls_back(self):
        assert sessions._safe_name("") == "default"

    def test_session_file_is_under_state_dir(self, tmp_state_home):
        path = sessions.session_file("work")
        assert str(tmp_state_home) in str(path)
        assert path.suffix == ".json"


class TestRecordAndLoad:
    def test_record_creates_file(self, tmp_state_home):
        sess = _make(pid=os.getpid())
        path = sessions.record(sess)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["profile"] == "work"
        assert data["pid"] == os.getpid()

    def test_record_sets_owner_only_mode(self, tmp_state_home):
        if os.name == "nt":
            pytest.skip("POSIX permissions only")
        sess = _make(pid=os.getpid())
        path = sessions.record(sess)
        assert oct(path.stat().st_mode)[-3:] == "600"

    def test_load_returns_live_session(self, tmp_state_home):
        sessions.record(_make(pid=os.getpid()))
        loaded = sessions.load("work")
        assert loaded is not None
        assert loaded.pid == os.getpid()

    def test_load_returns_none_for_missing(self, tmp_state_home):
        assert sessions.load("nope") is None

    def test_load_prunes_stale_record(self, tmp_state_home):
        # Use an unlikely-to-exist pid (very high)
        sessions.record(_make(pid=999999))
        assert sessions.load("work") is None
        # File should have been removed
        assert not sessions.session_file("work").exists()


class TestListActive:
    def test_empty_when_no_state_dir(self, tmp_state_home):
        # State dir doesn't exist yet
        assert sessions.list_active() == []

    def test_lists_live_sessions(self, tmp_state_home):
        sessions.record(_make(profile="work", pid=os.getpid()))
        sessions.record(_make(profile="lab", pid=os.getpid(), server="lab.example.com"))
        active = sessions.list_active()
        assert len(active) == 2
        names = sorted(s.profile for s in active)
        assert names == ["lab", "work"]

    def test_prunes_stale_during_listing(self, tmp_state_home):
        sessions.record(_make(profile="alive", pid=os.getpid()))
        sessions.record(_make(profile="ghost", pid=999999))
        active = sessions.list_active()
        assert [s.profile for s in active] == ["alive"]
        # Ghost file should have been cleaned up
        assert not sessions.session_file("ghost").exists()


class TestRemove:
    def test_remove_existing(self, tmp_state_home):
        sessions.record(_make(pid=os.getpid()))
        assert sessions.remove("work") is True
        assert not sessions.session_file("work").exists()

    def test_remove_missing_is_noop(self, tmp_state_home):
        assert sessions.remove("nope") is False


class TestKill:
    def test_kill_returns_false_when_no_record(self, tmp_state_home):
        assert sessions.kill("nope") is False

    def test_kill_signals_recorded_pid(self, tmp_state_home, monkeypatch):
        # Record a session for our own pid; intercept os.kill so we don't
        # actually kill the test runner.
        sessions.record(_make(pid=os.getpid()))
        signals_sent = []

        def fake_kill(pid, sig):
            if sig == 0:
                # liveness probe — pretend the process dies after the first
                # SIGTERM by raising ProcessLookupError on the next probe
                if signals_sent:
                    raise ProcessLookupError
                return
            signals_sent.append((pid, sig))

        monkeypatch.setattr(sessions.os, "kill", fake_kill)
        assert sessions.kill("work", timeout=0.5) is True
        assert signals_sent
        assert signals_sent[0][0] == os.getpid()
        # Record should be cleaned up
        assert not sessions.session_file("work").exists()
