"""Tests for the connection history log."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from openconnect_saml import history


class TestParseSince:
    def test_relative_minutes(self):
        result = history._parse_since("30 minutes ago")
        assert result is not None
        delta = (history.datetime.now(tz=history.timezone.utc) - result).total_seconds()
        # within 5 seconds of 30 minutes
        assert 30 * 60 - 5 < delta < 30 * 60 + 5

    def test_relative_hours_singular(self):
        result = history._parse_since("1 hour ago")
        assert result is not None
        delta = (history.datetime.now(tz=history.timezone.utc) - result).total_seconds()
        assert abs(delta - 3600) < 5

    def test_relative_days(self):
        result = history._parse_since("3 days ago")
        assert result is not None
        delta = (history.datetime.now(tz=history.timezone.utc) - result).total_seconds()
        assert abs(delta - 3 * 86400) < 5

    def test_iso_8601(self):
        result = history._parse_since("2026-04-30T12:00:00+00:00")
        assert result is not None
        assert result.year == 2026
        assert result.hour == 12

    def test_returns_none_on_garbage(self):
        assert history._parse_since("yesterday") is None
        assert history._parse_since("not a date") is None
        assert history._parse_since("five hours ago") is None


class TestReadHistoryFilters:
    def test_filter_by_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        history.log_event("connected", "vpn1.example.com", profile="work")
        history.log_event("connected", "vpn2.example.com", profile="lab")
        history.log_event("disconnected", "vpn1.example.com", profile="work")
        out = history.read_history(profile="work")
        assert len(out) == 2
        assert all(e["profile"] == "work" for e in out)

    def test_filter_by_event(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        history.log_event("connected", "vpn.example.com", profile="work")
        history.log_event("error", "vpn.example.com", profile="work", message="boom")
        history.log_event("disconnected", "vpn.example.com", profile="work")
        out = history.read_history(event="error")
        assert len(out) == 1
        assert out[0]["event"] == "error"

    def test_filter_combined(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        history.log_event("connected", "vpn.example.com", profile="work")
        history.log_event("connected", "vpn.example.com", profile="lab")
        history.log_event("error", "vpn.example.com", profile="work", message="x")
        out = history.read_history(profile="work", event="connected")
        assert len(out) == 1
        assert out[0]["profile"] == "work"
        assert out[0]["event"] == "connected"

    def test_since_filter_ignores_old(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        history.log_event("connected", "vpn.example.com", profile="work")
        # since=now-1s should still include the just-logged entry
        out = history.read_history(since="1 minute ago")
        assert len(out) == 1


class TestStats:
    def test_compute_stats_empty(self):
        s = history.compute_stats([])
        assert s["total_connections"] == 0
        assert s["total_seconds"] == 0
        assert s["avg_seconds"] == 0
        assert s["error_count"] == 0
        assert s["profiles"] == []
        assert s["most_used_profile"] is None

    def test_compute_stats_basic(self):
        entries = [
            {"event": "connected", "profile": "work", "timestamp": "2026-04-01T10:00:00+00:00"},
            {"event": "disconnected", "duration_seconds": 600.0},
            {"event": "connected", "profile": "work", "timestamp": "2026-04-02T10:00:00+00:00"},
            {"event": "disconnected", "duration_seconds": 1200.0},
            {"event": "connected", "profile": "home", "timestamp": "2026-04-03T10:00:00+00:00"},
            {"event": "disconnected", "duration_seconds": 300.0},
            {"event": "error", "message": "boom"},
        ]
        s = history.compute_stats(entries)
        assert s["total_connections"] == 3
        assert s["total_seconds"] == 2100.0
        assert s["avg_seconds"] == 700.0
        assert s["error_count"] == 1
        assert s["most_used_profile"] == "work"
        assert s["last_connected"] == "2026-04-03T10:00:00+00:00"
        # Profiles sorted by count desc
        assert s["profiles"][0] == {"name": "work", "count": 2}
        assert s["profiles"][1] == {"name": "home", "count": 1}

    def test_compute_stats_skips_invalid_duration(self):
        entries = [
            {"event": "connected", "profile": "p1"},
            {"event": "disconnected", "duration_seconds": "not a number"},
            {"event": "disconnected", "duration_seconds": 100.0},
        ]
        s = history.compute_stats(entries)
        assert s["total_seconds"] == 100.0
        assert s["avg_seconds"] == 100.0

    def test_handle_history_stats(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        history.log_event("connected", "vpn.example.com", profile="work")
        history.log_event("disconnected", "vpn.example.com", duration_seconds=120.0)
        args = SimpleNamespace(history_action="stats", json=False)
        rc = history.handle_history_command(args)
        out = capsys.readouterr().out
        assert rc == 0
        assert "Total connections : 1" in out
        assert "Profile usage:" in out
        assert "work" in out

    def test_handle_history_stats_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        history.log_event("connected", "vpn.example.com", profile="work")
        args = SimpleNamespace(history_action="stats", json=True)
        history.handle_history_command(args)
        payload = json.loads(capsys.readouterr().out)
        assert payload["total_connections"] == 1
        assert payload["most_used_profile"] == "work"


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
