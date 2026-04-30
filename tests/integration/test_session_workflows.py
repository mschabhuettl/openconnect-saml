"""End-to-end tests for the sessions / disconnect / history subcommands.

These run real subprocesses against an isolated config dir and exercise
flows that pure-unit tests don't (multi-process state propagation,
profile auto-save, history rotation thresholds, etc.).
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec
import sys

import pytest


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("OPENCONNECT_SAML_CONFIG", str(tmp_path / "config.toml"))
    yield tmp_path


def _cli(*argv, stdin_input=None, timeout=10):
    return subprocess.run(  # nosec
        [sys.executable, "-m", "openconnect_saml.cli", *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ},
        input=stdin_input,
    )


@pytest.mark.integration
class TestSessionsCLI:
    def test_sessions_list_empty(self, isolated):
        r = _cli("sessions", "list")
        assert r.returncode == 0
        assert "No active sessions" in r.stdout

    def test_sessions_list_json_empty(self, isolated):
        r = _cli("sessions", "list", "--json")
        assert r.returncode == 0
        # Empty list, JSON array
        assert json.loads(r.stdout) == []

    def test_disconnect_with_no_sessions(self, isolated):
        r = _cli("disconnect")
        assert r.returncode == 0  # `--all` with no sessions returns 0 ("nothing to do")
        assert "No active sessions" in r.stdout

    def test_disconnect_unknown_profile_fuzzy(self, isolated):
        # Need at least one recorded session for the fuzzy match. Without one,
        # the command bails with rc=1 and a clean error.
        r = _cli("disconnect", "ghost")
        assert r.returncode == 1


@pytest.mark.integration
class TestHistoryCLI:
    def test_history_show_empty(self, isolated):
        r = _cli("history", "show")
        assert r.returncode == 0
        assert "No history entries" in r.stdout

    def test_history_path(self, isolated):
        r = _cli("history", "path")
        assert r.returncode == 0
        assert "history.jsonl" in r.stdout

    def test_history_clear_when_empty(self, isolated):
        r = _cli("history", "clear")
        assert r.returncode == 0
        assert "already empty" in r.stdout or "cleared" in r.stdout.lower()

    def test_history_stats_empty(self, isolated):
        r = _cli("history", "stats")
        assert r.returncode == 0
        assert "Total connections" in r.stdout

    def test_history_stats_json_empty(self, isolated):
        r = _cli("history", "stats", "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["total_connections"] == 0


@pytest.mark.integration
class TestConfigCLI:
    def test_config_path(self, isolated):
        r = _cli("config", "path")
        assert r.returncode == 0
        assert "config.toml" in r.stdout

    def test_config_validate_no_file(self, isolated):
        r = _cli("config", "validate")
        # No config yet → validate reports "not found" with rc=1
        assert r.returncode == 1
        assert "not found" in r.stdout.lower() or "not found" in r.stderr.lower()

    def test_config_show_when_missing(self, isolated):
        r = _cli("config", "show")
        # Show emits "no config" rather than crashing
        assert r.returncode == 1


@pytest.mark.integration
class TestGroupsCLI:
    def test_groups_list_empty(self, isolated):
        r = _cli("groups", "list")
        assert r.returncode == 0
        assert "No profile groups" in r.stdout

    def test_groups_full_lifecycle(self, isolated):
        # Add a couple of profiles first
        _cli("profiles", "add", "eu", "--server", "vpn-eu.example.com")
        _cli("profiles", "add", "us", "--server", "vpn-us.example.com")
        # Add a group
        r = _cli("groups", "add", "work", "eu", "us")
        assert r.returncode == 0
        # List shows it
        r = _cli("groups", "list")
        assert "work" in r.stdout
        # Rename
        r = _cli("groups", "rename", "work", "office")
        assert r.returncode == 0
        # Old name is gone, new is present
        r = _cli("groups", "list")
        assert "office" in r.stdout
        assert "work" not in r.stdout
        # Remove
        r = _cli("groups", "remove", "office")
        assert r.returncode == 0


@pytest.mark.integration
class TestDoctorCLI:
    def test_doctor_runs(self, isolated):
        r = _cli("doctor")
        # 0 / 1 / 2 depending on the environment; just confirm clean exit
        assert r.returncode in (0, 1, 2)
        # Either text output or skipped checks must appear
        assert "Python" in r.stdout

    def test_doctor_json_structure(self, isolated):
        r = _cli("doctor", "--json")
        assert r.returncode in (0, 1, 2)
        data = json.loads(r.stdout)
        assert "summary" in data
        assert "checks" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) > 0
        # Each check must have name + status fields
        for c in data["checks"]:
            assert "name" in c
            assert "status" in c


@pytest.mark.integration
class TestProfileMigrate:
    def test_migrate_dry_run_clean_config(self, isolated):
        # Add a profile via the CLI, then migrate should be a no-op
        _cli("profiles", "add", "work", "--server", "vpn.example.com")
        r = _cli("profiles", "migrate")
        assert r.returncode == 0
        # Either "no migrations needed" or applied schema_version bump
        assert (
            "No migrations needed" in r.stdout or "schema_version" in r.stdout or "Bump" in r.stdout
        )

    def test_migrate_apply(self, isolated):
        _cli("profiles", "add", "work", "--server", "vpn.example.com")
        r = _cli("profiles", "migrate", "--apply")
        assert r.returncode == 0
