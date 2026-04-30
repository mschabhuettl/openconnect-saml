"""Tests filling in small coverage gaps across several modules.

These are deliberately small, focused unit tests for code paths that
the main per-module test files happened to miss — error/fallback
branches, single-statement modules, and a couple of helpers that are
easy to exercise in isolation.
"""

from __future__ import annotations

import asyncio
import builtins
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# version.py — single-statement module, just confirm the constant is exposed
# ---------------------------------------------------------------------------


class TestVersionModule:
    def test_version_constant_is_a_string(self):
        from openconnect_saml import version as v

        assert isinstance(v.__version__, str)
        assert v.__version__  # non-empty

    def test_package_exposes_version_from_metadata(self):
        # The runtime ``openconnect_saml.__version__`` comes from package
        # metadata, not from ``openconnect_saml.version`` (which is a stale
        # backup constant). Just assert both look like a dotted-numeric
        # version string.
        import re

        import openconnect_saml as pkg
        from openconnect_saml import version as v

        version_re = re.compile(r"^\d+\.\d+(\.\d+)?")
        assert version_re.match(pkg.__version__)
        assert version_re.match(v.__version__)


# ---------------------------------------------------------------------------
# version_check.py — cover the requests-import-error and malformed-payload
# branches that the existing test file doesn't reach.
# ---------------------------------------------------------------------------


class TestVersionCheckExtras:
    def test_returns_none_when_requests_missing(self):
        """Lines 59-60: ImportError on `import requests` → returns None."""
        from openconnect_saml import version_check as vc

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "requests":
                raise ImportError("simulated missing requests")
            return real_import(name, *args, **kwargs)

        # Force re-import inside the function by removing any cached requests
        with patch.object(builtins, "__import__", side_effect=fake_import):
            sys.modules.pop("requests", None)
            assert vc.get_latest_pypi_version() is None

    def test_returns_none_when_info_field_not_dict(self):
        """Line 69: malformed PyPI payload where `info` isn't a dict."""
        from openconnect_saml import version_check as vc

        fake_response = MagicMock()
        fake_response.json.return_value = {"info": "not a dict"}
        fake_response.raise_for_status.return_value = None
        with patch("requests.get", return_value=fake_response):
            assert vc.get_latest_pypi_version() is None

    def test_returns_none_when_payload_not_dict(self):
        """Line 67-69: top-level payload that isn't even a dict."""
        from openconnect_saml import version_check as vc

        fake_response = MagicMock()
        fake_response.json.return_value = ["not", "a", "dict"]
        fake_response.raise_for_status.return_value = None
        with patch("requests.get", return_value=fake_response):
            assert vc.get_latest_pypi_version() is None

    def test_returns_none_when_version_field_not_string(self):
        from openconnect_saml import version_check as vc

        fake_response = MagicMock()
        fake_response.json.return_value = {"info": {"version": 123}}
        fake_response.raise_for_status.return_value = None
        with patch("requests.get", return_value=fake_response):
            assert vc.get_latest_pypi_version() is None


# ---------------------------------------------------------------------------
# notify.py — cover the macOS subprocess-error branch and the
# notify_disconnected branch that includes the profile name.
# ---------------------------------------------------------------------------


class TestNotifyExtras:
    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/osascript")
    @patch(
        "openconnect_saml.notify.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="osascript", timeout=5),
    )
    def test_macos_handles_timeout(self, mock_run, mock_which):
        """Lines 76-77: osascript subprocess timeout returns False."""
        from openconnect_saml.notify import _notify_macos

        assert _notify_macos("Test", "Hello") is False

    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/osascript")
    @patch("openconnect_saml.notify.subprocess.run", side_effect=OSError("no permission"))
    def test_macos_handles_oserror(self, mock_run, mock_which):
        from openconnect_saml.notify import _notify_macos

        assert _notify_macos("Test", "Hello") is False

    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/osascript")
    @patch("openconnect_saml.notify.subprocess.run")
    def test_macos_escapes_quotes_and_backslashes(self, mock_run, mock_which):
        from openconnect_saml.notify import _notify_macos

        mock_run.return_value = MagicMock(returncode=0)
        assert _notify_macos('Hello "World"', "Back\\slash") is True
        # Inspect the AppleScript built — must escape both characters
        script = mock_run.call_args[0][0][2]
        assert '\\"World\\"' in script
        assert "Back\\\\slash" in script

    @patch("openconnect_saml.notify.send_notification")
    def test_notify_disconnected_with_profile(self, mock_send):
        """Line 134: profile-name branch in notify_disconnected."""
        from openconnect_saml.notify import notify_disconnected

        notify_disconnected("vpn.example.com", "work")
        msg = mock_send.call_args[0][1]
        assert "work" in msg
        assert "vpn.example.com" in msg


# ---------------------------------------------------------------------------
# profile.py — cover the malformed-HostEntry skip path (lines 37-38).
# ---------------------------------------------------------------------------


class TestProfileMalformedEntry:
    def test_malformed_host_entry_skipped(self, tmp_path):
        """An entry that raises during HostProfile construction is skipped,
        not propagated, and the rest of the file still parses."""
        profile = tmp_path / "mixed.xml"
        # The first entry has a HostName subtree (lxml.objectify returns
        # an ObjectifiedElement, not str) which makes ``str(...)`` work
        # fine, so to actually trigger the AttributeError/TypeError
        # branch we patch HostProfile to raise on the first call.
        profile.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>Bad</HostName>
      <HostAddress>bad.example.com</HostAddress>
      <UserGroup>g</UserGroup>
    </HostEntry>
    <HostEntry>
      <HostName>Good</HostName>
      <HostAddress>good.example.com</HostAddress>
      <UserGroup>g</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>""")

        from openconnect_saml import profile as profile_mod

        real = profile_mod.HostProfile
        calls = {"n": 0}

        def flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise AttributeError("simulated bad HostEntry")
            return real(**kwargs)

        with patch.object(profile_mod, "HostProfile", side_effect=flaky):
            result = profile_mod._get_profiles_from_one_file(profile)

        assert len(result) == 1
        assert result[0].name == "Good"


# ---------------------------------------------------------------------------
# encrypted_backup.py — cover stdout target, write OSError, magic mismatch,
# prompt-confirm path, and import-with-prompt.
# ---------------------------------------------------------------------------


class TestEncryptedBackupExtras:
    def test_decrypt_rejects_wrong_magic(self):
        """Line 72: file with valid layout but wrong magic header."""
        from openconnect_saml import encrypted_backup as eb

        bad = b"WRONG_MAGIC\nv1\nAAAA\nXXXX\n"
        with pytest.raises(ValueError, match="Not an openconnect-saml backup"):
            eb.decrypt(bad, "any")

    def test_export_to_stdout(self, capfd):
        """Lines 110-111: target=None writes raw bytes to fd 1."""
        from openconnect_saml import encrypted_backup as eb

        rc = eb.export_encrypted({"x": 1}, target=None, passphrase="pw")
        assert rc == 0
        out, _ = capfd.readouterr()
        assert out.startswith(eb.MAGIC)

    def test_export_to_dash_writes_stdout(self, capfd):
        from openconnect_saml import encrypted_backup as eb

        rc = eb.export_encrypted({"x": 1}, target=Path("-"), passphrase="pw")
        assert rc == 0
        out, _ = capfd.readouterr()
        assert eb.MAGIC in out

    def test_export_handles_write_error(self, tmp_path, capsys):
        """Lines 118-120: OSError while writing the target returns 1."""
        from openconnect_saml import encrypted_backup as eb

        target = tmp_path / "sub" / "backup.enc"  # parent doesn't exist

        with patch.object(Path, "write_bytes", side_effect=OSError("disk full")):
            rc = eb.export_encrypted({"x": 1}, target=target, passphrase="pw")

        assert rc == 1
        err = capsys.readouterr().err
        assert "disk full" in err

    def test_prompt_passphrase_empty_exits(self):
        """Lines 86-88: empty passphrase aborts with sys.exit(1)."""
        from openconnect_saml import encrypted_backup as eb

        with patch("getpass.getpass", return_value=""), pytest.raises(SystemExit) as excinfo:
            eb._prompt_passphrase()
        assert excinfo.value.code == 1

    def test_prompt_passphrase_mismatch_exits(self):
        """Lines 90-93: confirm step that doesn't match aborts."""
        from openconnect_saml import encrypted_backup as eb

        # First call returns "a", second (confirm) returns "b"
        with (
            patch("getpass.getpass", side_effect=["a", "b"]),
            pytest.raises(SystemExit) as excinfo,
        ):
            eb._prompt_passphrase(confirm=True)
        assert excinfo.value.code == 1

    def test_prompt_passphrase_success(self):
        from openconnect_saml import encrypted_backup as eb

        with patch("getpass.getpass", side_effect=["secret", "secret"]):
            assert eb._prompt_passphrase(confirm=True) == "secret"

    def test_export_uses_prompt_when_no_passphrase(self, tmp_path):
        """Line 106: passphrase=None falls back to the interactive prompt."""
        from openconnect_saml import encrypted_backup as eb

        target = tmp_path / "b.enc"
        with patch.object(eb, "_prompt_passphrase", return_value="pw") as p:
            rc = eb.export_encrypted({"x": 1}, target=target)
        assert rc == 0
        p.assert_called_once_with(confirm=True)
        # Round trip
        assert eb.import_encrypted(target, passphrase="pw") == {"x": 1}

    def test_import_uses_prompt_when_no_passphrase(self, tmp_path):
        """Line 128: passphrase=None on import → interactive prompt without confirm."""
        from openconnect_saml import encrypted_backup as eb

        target = tmp_path / "b.enc"
        eb.export_encrypted({"y": 2}, target=target, passphrase="pw")

        with patch.object(eb, "_prompt_passphrase", return_value="pw") as p:
            payload = eb.import_encrypted(target)
        p.assert_called_once_with(confirm=False)
        assert payload == {"y": 2}


# ---------------------------------------------------------------------------
# saml_authenticator.py — cover both the missing-PyQt branch and the happy
# path with a fully mocked Browser.
# ---------------------------------------------------------------------------


class TestSamlAuthenticator:
    def test_raises_importerror_when_browser_unavailable(self):
        """Lines 11-15: helpful ImportError when PyQt6 isn't installed."""
        from openconnect_saml import saml_authenticator as sa

        with patch.object(sa, "Browser", None), pytest.raises(ImportError, match="PyQt6"):
            asyncio.run(
                sa.authenticate_in_browser(
                    proxy=None,
                    auth_info=MagicMock(),
                    credentials=MagicMock(),
                    display_mode="SHOWN",
                )
            )

    def test_happy_path_returns_token_cookie(self):
        """Lines 17-26: drives the async loop with a fake Browser."""
        from openconnect_saml import saml_authenticator as sa

        auth_info = MagicMock()
        auth_info.login_url = "https://idp.example.com/login"
        auth_info.login_final_url = "https://vpn.example.com/+CSCOE+/done"
        auth_info.token_cookie_name = "webvpn"

        # Fake Browser used as `async with Browser(...) as browser`
        class FakeBrowser:
            def __init__(self, *a, **kw):
                self.url = None
                self.cookies = {"webvpn": "TOKEN-VALUE"}
                self._steps = iter(["https://idp.example.com/step1", auth_info.login_final_url])

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def authenticate_at(self, url, credentials):
                assert url == auth_info.login_url

            async def page_loaded(self):
                self.url = next(self._steps)

        with patch.object(sa, "Browser", FakeBrowser):
            token = asyncio.run(
                sa.authenticate_in_browser(
                    proxy=None,
                    auth_info=auth_info,
                    credentials=MagicMock(),
                    display_mode="SHOWN",
                    window_width=1024,
                    window_height=768,
                )
            )

        assert token == "TOKEN-VALUE"


# ---------------------------------------------------------------------------
# browser package — Terminated exception is exposed even without PyQt.
# ---------------------------------------------------------------------------


class TestBrowserPackage:
    def test_terminated_is_exception_subclass(self):
        from openconnect_saml.browser import Terminated

        assert issubclass(Terminated, Exception)

    def test_terminated_can_be_raised_and_caught(self):
        from openconnect_saml.browser import Terminated

        with pytest.raises(Terminated):
            raise Terminated("browser closed")


# ---------------------------------------------------------------------------
# sessions.py — error / edge branches.
# ---------------------------------------------------------------------------


class TestSessionsExtras:
    @pytest.fixture(autouse=True)
    def _state(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        self.tmp = tmp_path

    def test_pid_alive_rejects_non_positive(self):
        from openconnect_saml import sessions

        assert sessions._pid_alive(0) is False
        assert sessions._pid_alive(-1) is False

    def test_pid_alive_treats_permissionerror_as_alive(self, monkeypatch):
        from openconnect_saml import sessions

        def raise_perm(pid, sig):
            raise PermissionError("not your process")

        monkeypatch.setattr(sessions.os, "kill", raise_perm)
        assert sessions._pid_alive(12345) is True

    def test_record_swallows_oserror(self, monkeypatch):
        from openconnect_saml import sessions

        # Make write_text raise OSError. record() should log a warning and
        # still return the (would-be) path rather than re-raising.
        def boom(self, *a, **kw):
            raise OSError("disk full")

        monkeypatch.setattr("pathlib.Path.write_text", boom)
        sess = sessions.Session(profile="work", server="vpn.example.com", pid=os.getpid())
        path = sessions.record(sess)
        assert path == sessions.session_file("work")
        assert not path.exists()

    def test_load_returns_none_on_corrupt_json(self):
        from openconnect_saml import sessions

        path = sessions.session_file("corrupt")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text("{ this is not json")
        assert sessions.load("corrupt") is None

    def test_list_active_skips_corrupt_files(self):
        from openconnect_saml import sessions

        # One good live record + one corrupt JSON file in the dir
        sessions.record(sessions.Session(profile="alive", server="s", pid=os.getpid()))
        bad = sessions._state_dir() / "broken.json"
        bad.write_text("{ not json")
        active = sessions.list_active()
        assert [s.profile for s in active] == ["alive"]
        # Corrupt file should be left in place (we can't tell what to do
        # with it); the real cleanup is for stale-but-valid records.
        assert bad.exists()

    def test_kill_returns_false_on_processlookuperror(self, monkeypatch):
        from openconnect_saml import sessions

        sessions.record(sessions.Session(profile="ghost", server="s", pid=os.getpid()))

        def raise_lookup(pid, sig):
            if sig == 0:
                # liveness probe — pretend it's alive so load() succeeds
                return
            raise ProcessLookupError

        monkeypatch.setattr(sessions.os, "kill", raise_lookup)
        assert sessions.kill("ghost", timeout=0.1) is False
        assert not sessions.session_file("ghost").exists()

    def test_kill_escalates_to_sigkill_when_term_ignored(self, monkeypatch):
        """If SIGTERM doesn't kill the process within the timeout, kill()
        sends SIGKILL and removes the record."""
        import signal as _signal

        from openconnect_saml import sessions

        sessions.record(sessions.Session(profile="zombie", server="s", pid=os.getpid()))
        sent = []

        def fake_kill(pid, sig):
            sent.append(sig)
            # Liveness probes always report alive, so SIGTERM polling
            # times out and we escalate.
            return

        monkeypatch.setattr(sessions.os, "kill", fake_kill)
        # tiny timeout so the test is fast
        assert sessions.kill("zombie", timeout=0.05) is True
        assert _signal.SIGTERM in sent
        assert _signal.SIGKILL in sent
        assert not sessions.session_file("zombie").exists()


# ---------------------------------------------------------------------------
# completion.py — group/session/install branches.
# ---------------------------------------------------------------------------


class TestCompletionExtras:
    def test_get_group_names_with_groups(self):
        from openconnect_saml import completion

        cfg = MagicMock()
        cfg.profile_groups = {"prod": ["work"], "lab": ["dev"]}
        with patch.object(completion.config, "load", return_value=cfg):
            names = completion._get_group_names()
        assert sorted(names) == ["lab", "prod"]

    def test_get_group_names_handles_load_error(self):
        from openconnect_saml import completion

        with patch.object(completion.config, "load", side_effect=RuntimeError("nope")):
            assert completion._get_group_names() == []

    def test_get_session_names(self):
        from openconnect_saml import completion

        fake = [MagicMock(profile="work"), MagicMock(profile="lab")]
        with patch("openconnect_saml.sessions.list_active", return_value=fake):
            assert completion._get_session_names() == ["work", "lab"]

    def test_get_session_names_swallows_errors(self):
        from openconnect_saml import completion

        with patch("openconnect_saml.sessions.list_active", side_effect=OSError("no state")):
            assert completion._get_session_names() == []

    def test_handle_completion_groups_branch(self, capsys):
        from openconnect_saml import completion

        args = MagicMock()
        args.shell_type = "_groups"
        with patch.object(completion, "_get_group_names", return_value=["prod", "lab"]):
            assert completion.handle_completion_command(args) == 0
        out = capsys.readouterr().out.split()
        assert out == ["prod", "lab"]

    def test_handle_completion_sessions_branch(self, capsys):
        from openconnect_saml import completion

        args = MagicMock()
        args.shell_type = "_sessions"
        with patch.object(completion, "_get_session_names", return_value=["work"]):
            assert completion.handle_completion_command(args) == 0
        assert capsys.readouterr().out.strip() == "work"

    def test_install_writes_completion_files(self, tmp_path, monkeypatch, capsys):
        """Exercise _install_completions end-to-end against a fake $HOME."""
        from openconnect_saml import completion

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
        args = MagicMock()
        args.shell_type = "install"

        rc = completion.handle_completion_command(args)
        assert rc == 0

        assert (
            tmp_path / ".local" / "share" / "bash-completion" / "completions" / "openconnect-saml"
        ).exists()
        assert (tmp_path / ".zsh" / "completions" / "_openconnect-saml").exists()
        assert (tmp_path / ".config" / "fish" / "completions" / "openconnect-saml.fish").exists()

        out = capsys.readouterr().out
        assert "Installed shell completions" in out
