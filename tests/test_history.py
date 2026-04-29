"""Tests for the connection history log."""

from __future__ import annotations

import json
import os

import pytest

from openconnect_saml import history


@pytest.fixture
def tmp_state_home(tmp_path, monkeypatch):
    """Redirect XDG_STATE_HOME to a temp dir for isolated tests."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    yield tmp_path


def test_history_path_uses_xdg(tmp_state_home):
    path = history.history_path()
    assert str(tmp_state_home) in str(path)
    assert path.name == "history.jsonl"


def test_log_event_creates_file(tmp_state_home):
    history.log_event("connected", "vpn.example.com", profile="work", user="alice")
    entries = history.read_history()
    assert len(entries) == 1
    assert entries[0]["event"] == "connected"
    assert entries[0]["server"] == "vpn.example.com"
    assert entries[0]["profile"] == "work"
    assert entries[0]["user"] == "alice"
    assert "timestamp" in entries[0]


def test_log_event_append(tmp_state_home):
    history.log_event("connected", "vpn.example.com")
    history.log_event("disconnected", "vpn.example.com", duration_seconds=42.5)
    entries = history.read_history()
    assert len(entries) == 2
    assert entries[0]["event"] == "connected"
    assert entries[1]["event"] == "disconnected"
    assert entries[1]["duration_seconds"] == 42.5


def test_read_history_with_limit(tmp_state_home):
    for i in range(5):
        history.log_event("connected", f"vpn{i}.example.com")
    entries = history.read_history(limit=2)
    assert len(entries) == 2
    # read_history returns newest-last, so the last two should be vpn3/vpn4
    assert entries[0]["server"] == "vpn3.example.com"
    assert entries[1]["server"] == "vpn4.example.com"


def test_read_history_empty(tmp_state_home):
    assert history.read_history() == []


def test_clear_history(tmp_state_home):
    history.log_event("connected", "vpn.example.com")
    assert history.clear_history() is True
    assert history.read_history() == []
    # Second clear is a no-op
    assert history.clear_history() is False


def test_history_file_permissions(tmp_state_home):
    history.log_event("connected", "vpn.example.com")
    path = history.history_path()
    if os.name == "posix":
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_rotation_on_large_file(tmp_state_home, monkeypatch):
    # Shrink rotation threshold for the test
    monkeypatch.setattr(history, "MAX_SIZE_BYTES", 100)
    for i in range(20):
        history.log_event("connected", f"vpn{i}.example.com" + "x" * 50)
    # Old file should exist after rotation
    old = history.history_path().with_suffix(".jsonl.old")
    assert old.exists()


def test_read_history_ignores_bad_lines(tmp_state_home):
    history.log_event("connected", "vpn.example.com")
    # Manually append garbage
    with history.history_path().open("a") as f:
        f.write("this is not json\n")
    history.log_event("disconnected", "vpn.example.com")
    entries = history.read_history()
    # Bad line is skipped, not errored
    assert len(entries) == 2


class TestConnectionTracker:
    def test_full_lifecycle(self, tmp_state_home):
        tracker = history.ConnectionTracker(server="vpn.example.com", profile="work", user="alice")
        tracker.start()
        tracker.stop("clean exit")
        entries = history.read_history()
        assert len(entries) == 2
        assert entries[0]["event"] == "connected"
        assert entries[1]["event"] == "disconnected"
        assert entries[1]["message"] == "clean exit"
        # duration should be captured (even if tiny)
        assert entries[1]["duration_seconds"] is not None
        assert entries[1]["duration_seconds"] >= 0

    def test_reconnecting(self, tmp_state_home):
        tracker = history.ConnectionTracker(server="vpn.example.com")
        tracker.start()
        tracker.reconnecting(attempt=2, delay=60)
        entries = history.read_history()
        assert entries[-1]["event"] == "reconnecting"
        assert "attempt=2" in entries[-1]["message"]
        assert "delay=60s" in entries[-1]["message"]

    def test_error_event(self, tmp_state_home):
        tracker = history.ConnectionTracker(server="vpn.example.com")
        tracker.error("something broke")
        entries = history.read_history()
        assert entries[-1]["event"] == "error"
        assert entries[-1]["message"] == "something broke"

    def test_stop_without_start(self, tmp_state_home):
        tracker = history.ConnectionTracker(server="vpn.example.com")
        tracker.stop()
        entries = history.read_history()
        assert len(entries) == 1
        assert entries[0]["event"] == "disconnected"
        assert entries[0]["duration_seconds"] is None


class TestHandleHistoryCommand:
    def test_show_empty(self, tmp_state_home, capsys):
        class Args:
            history_action = "show"
            limit = None
            json = False

        rc = history.handle_history_command(Args())
        assert rc == 0
        captured = capsys.readouterr()
        assert "No history entries" in captured.out

    def test_show_with_entries(self, tmp_state_home, capsys):
        history.log_event("connected", "vpn.example.com", profile="work")

        class Args:
            history_action = "show"
            limit = None
            json = False

        rc = history.handle_history_command(Args())
        assert rc == 0
        captured = capsys.readouterr()
        assert "connected" in captured.out
        assert "vpn.example.com" in captured.out

    def test_show_json(self, tmp_state_home, capsys):
        history.log_event("connected", "vpn.example.com")

        class Args:
            history_action = "show"
            limit = None
            json = True

        rc = history.handle_history_command(Args())
        assert rc == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert isinstance(parsed, list)
        assert parsed[0]["event"] == "connected"

    def test_clear(self, tmp_state_home, capsys):
        history.log_event("connected", "vpn.example.com")

        class Args:
            history_action = "clear"

        rc = history.handle_history_command(Args())
        assert rc == 0
        assert history.read_history() == []

    def test_path(self, tmp_state_home, capsys):
        class Args:
            history_action = "path"

        rc = history.handle_history_command(Args())
        assert rc == 0
        captured = capsys.readouterr()
        assert "history.jsonl" in captured.out
