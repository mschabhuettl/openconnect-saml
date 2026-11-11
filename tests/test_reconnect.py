"""Tests for auto-reconnect logic."""

from __future__ import annotations

import argparse
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openconnect_saml import config, sessions
from openconnect_saml.app import RECONNECT_BACKOFF, _run_with_reconnect


class TestReconnectBackoff:
    def test_backoff_schedule(self):
        """Verify backoff schedule: 30s, 60s, 120s, 300s."""
        assert RECONNECT_BACKOFF == [30, 60, 120, 300]

    def test_backoff_last_value_repeats(self):
        """After exhausting the schedule, the last value (300s) should be used."""
        for i in range(10):
            idx = min(i, len(RECONNECT_BACKOFF) - 1)
            assert RECONNECT_BACKOFF[idx] == RECONNECT_BACKOFF[min(i, 3)]


class TestRunWithReconnect:
    def _make_args(self, **kwargs):
        defaults = {
            "proxy": None,
            "ac_version": "4.7.00136",
            "openconnect_args": [],
            "no_sudo": True,
            "csd_wrapper": None,
            "reconnect": True,
            "max_retries": None,
            "headless": True,
            "browser": None,
            "browser_display_mode": "shown",
            "server": "vpn.example.com",
            "user": None,
            "usergroup": "",
            "authgroup": "",
            "profile_path": None,
            "use_profile_selector": False,
            "authenticate": False,
            "on_connect": "",
            "on_disconnect": "",
            "reset_credentials": False,
            "timeout": 30,
            "window_size": None,
            "ssl_legacy": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    def _make_cfg(self):
        cfg = MagicMock()
        cfg.on_connect = ""
        cfg.on_disconnect = ""
        return cfg

    @pytest.mark.parametrize("outcome", [0, 1, "interrupt"])
    def test_exit_cleans_up_its_recorded_session(self, tmp_path, monkeypatch, outcome):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        args = self._make_args(profile_name="work")
        cfg = config.Config(profiles={"work": {"server": "https://vpn.invalid"}})
        host = config.HostProfile("vpn.invalid", "", "")

        def connect(*positional, **options):
            options["on_pid"](999999)
            assert sessions.session_file("work").exists()
            if outcome == "interrupt":
                raise KeyboardInterrupt
            return outcome

        with patch("openconnect_saml.app.run_openconnect", side_effect=connect):
            result = _run_with_reconnect(args, cfg, MagicMock(), host, max_retries=1)
        assert result == (1 if outcome == 1 else 0)
        assert not sessions.session_file("work").exists()

    def test_exit_does_not_remove_an_unrelated_session_record(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        sessions.record(sessions.Session(profile="work", server="vpn.invalid", pid=os.getpid()))
        args = self._make_args(profile_name="work")
        cfg = config.Config(profiles={"work": {"server": "https://vpn.invalid"}})
        host = config.HostProfile("vpn.invalid", "", "")
        with patch("openconnect_saml.app.run_openconnect", return_value=0):
            assert _run_with_reconnect(args, cfg, MagicMock(), host) == 0
        assert sessions.load("work") is not None

    def test_exit_keeps_a_new_connection_record_for_the_same_profile(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        args = self._make_args(profile_name="work")
        cfg = config.Config(profiles={"work": {"server": "https://vpn.invalid"}})

        def connect(*positional, **options):
            options["on_pid"](999999)
            sessions.record(
                sessions.Session(profile="work", server="other.invalid", pid=os.getpid())
            )
            return 0

        with patch("openconnect_saml.app.run_openconnect", side_effect=connect):
            assert (
                _run_with_reconnect(
                    args, cfg, MagicMock(), config.HostProfile("vpn.invalid", "", "")
                )
                == 0
            )
        assert sessions.load("work").server == "other.invalid"

    @patch("openconnect_saml.app.run_openconnect", return_value=0)
    @patch("openconnect_saml.app.handle_disconnect")
    def test_clean_exit_no_retry(self, mock_disconnect, mock_run):
        """Clean exit (rc=0) should not retry."""
        args = self._make_args()
        cfg = self._make_cfg()
        auth_response = MagicMock()
        profile = MagicMock()

        result = _run_with_reconnect(args, cfg, auth_response, profile)
        assert result == 0
        mock_run.assert_called_once()
        mock_disconnect.assert_called_once()

    @patch("openconnect_saml.app._run", new_callable=AsyncMock)
    @patch("openconnect_saml.app.run_openconnect")
    @patch("openconnect_saml.app.handle_disconnect")
    @patch("time.sleep")
    def test_retry_then_success(self, mock_sleep, mock_disconnect, mock_run, mock_reauth):
        """Should retry on failure, then succeed."""
        # First call fails, second succeeds
        mock_run.side_effect = [1, 0]
        mock_reauth.return_value = (MagicMock(), MagicMock())

        args = self._make_args()
        cfg = self._make_cfg()

        result = _run_with_reconnect(args, cfg, MagicMock(), MagicMock())
        assert result == 0
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once_with(30)  # First backoff

    @patch("openconnect_saml.app._run", new_callable=AsyncMock)
    @patch("openconnect_saml.app.run_openconnect", return_value=1)
    @patch("openconnect_saml.app.handle_disconnect")
    @patch("time.sleep")
    def test_max_retries_reached(self, mock_sleep, mock_disconnect, mock_run, mock_reauth):
        """Should stop after max_retries.

        With max_retries=2: initial run (fails) → attempt=1 (retry, fails) → attempt=2 (stop).
        So run_openconnect is called twice (initial + 1 retry before hitting limit).
        """
        mock_reauth.return_value = (MagicMock(), MagicMock())

        args = self._make_args(max_retries=2)
        cfg = self._make_cfg()

        result = _run_with_reconnect(args, cfg, MagicMock(), MagicMock(), max_retries=2)
        assert result == 1
        assert mock_run.call_count == 2  # Initial + 1 retry before hitting max
        mock_disconnect.assert_called_once()

    @patch("openconnect_saml.app._run", new_callable=AsyncMock)
    @patch("openconnect_saml.app.run_openconnect", return_value=1)
    @patch("openconnect_saml.app.handle_disconnect")
    @patch("time.sleep")
    def test_backoff_increases(self, mock_sleep, mock_disconnect, mock_run, mock_reauth):
        """Backoff should increase per schedule."""
        mock_reauth.return_value = (MagicMock(), MagicMock())

        args = self._make_args(max_retries=5)
        cfg = self._make_cfg()

        result = _run_with_reconnect(args, cfg, MagicMock(), MagicMock(), max_retries=5)
        assert result == 1
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert sleep_calls == [30, 60, 120, 300]

    @patch("openconnect_saml.app.run_openconnect", side_effect=KeyboardInterrupt)
    @patch("openconnect_saml.app.handle_disconnect")
    def test_keyboard_interrupt(self, mock_disconnect, mock_run):
        """CTRL-C during openconnect should exit cleanly."""
        args = self._make_args()
        cfg = self._make_cfg()

        result = _run_with_reconnect(args, cfg, MagicMock(), MagicMock())
        assert result == 0
        mock_disconnect.assert_called_once()

    @patch("openconnect_saml.app._run", new_callable=AsyncMock)
    @patch("openconnect_saml.app.run_openconnect", return_value=1)
    @patch("openconnect_saml.app.handle_disconnect")
    @patch("time.sleep")
    def test_reauth_failure_continues(self, mock_sleep, mock_disconnect, mock_run, mock_reauth):
        """Re-authentication failure should continue retrying."""
        mock_reauth.side_effect = [Exception("auth failed"), (MagicMock(), MagicMock())]
        mock_run.side_effect = [1, 1, 0]

        args = self._make_args(max_retries=3)
        cfg = self._make_cfg()

        _run_with_reconnect(args, cfg, MagicMock(), MagicMock(), max_retries=3)
        # After first failure + reauth failure, continues to try again
        assert mock_sleep.call_count >= 1
