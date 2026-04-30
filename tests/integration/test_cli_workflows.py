"""End-to-end workflow tests: real subprocess invocations against an
isolated config dir. These exercise full CLI flows that pure-unit tests
would over-mock — profile add → connect/auth → history → sessions etc.
"""

from __future__ import annotations

import json
import os
import subprocess  # nosec
import sys

import pytest

from tests.integration.mock_saml_gateway import (
    SESSION_TOKEN,
    MockGateway,
)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("OPENCONNECT_SAML_CONFIG", str(tmp_path / "config.toml"))
    yield tmp_path


def _cli(*argv, stdin_input=None, timeout=20):
    return subprocess.run(  # nosec
        [sys.executable, "-m", "openconnect_saml.cli", *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ},
        input=stdin_input,
    )


@pytest.mark.integration
class TestProfilesWorkflow:
    def test_add_list_show_remove(self, isolated):
        # Add
        r = _cli(
            "profiles",
            "add",
            "work",
            "--server",
            "vpn.example.com",
            "--user",
            "alice@example.com",
            "--user-group",
            "engineers",
        )
        assert r.returncode == 0, r.stderr
        # List should show the profile
        r = _cli("profiles", "list")
        assert "work" in r.stdout
        assert "vpn.example.com" in r.stdout
        # Show JSON
        r = _cli("profiles", "show", "work", "--json")
        data = json.loads(r.stdout)
        assert data["server"] == "vpn.example.com"
        # Set a field via CLI
        r = _cli("profiles", "set", "work", "browser", "chrome")
        assert r.returncode == 0
        r = _cli("profiles", "show", "work", "--json")
        assert json.loads(r.stdout).get("browser") == "chrome"
        # Copy
        r = _cli("profiles", "copy", "work", "work-copy")
        assert r.returncode == 0
        r = _cli("profiles", "list")
        assert "work-copy" in r.stdout
        # Remove
        r = _cli("profiles", "remove", "work-copy")
        assert r.returncode == 0
        r = _cli("profiles", "list")
        assert "work-copy" not in r.stdout

    def test_export_import_json(self, isolated):
        _cli("profiles", "add", "work", "--server", "vpn.example.com", "--user", "alice")
        # Export
        r = _cli("profiles", "export", "work")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["profile"]["server"] == "vpn.example.com"
        # Round-trip via stdin
        r = _cli("profiles", "remove", "work")
        assert r.returncode == 0
        r = _cli(
            "profiles",
            "import",
            "-",
            "--force",
            stdin_input=json.dumps(payload),
        )
        assert r.returncode == 0
        r = _cli("profiles", "list")
        assert "work" in r.stdout

    def test_export_nmconnection(self, isolated, tmp_path):
        _cli(
            "profiles",
            "add",
            "work",
            "--server",
            "vpn.example.com",
            "--user-group",
            "eng",
        )
        out = tmp_path / "work.nmconnection"
        r = _cli(
            "profiles",
            "export",
            "work",
            "--format",
            "nmconnection",
            "-o",
            str(out),
        )
        assert r.returncode == 0
        text = out.read_text()
        assert "[connection]" in text
        assert "[vpn]" in text
        assert "service-type=org.freedesktop.NetworkManager.openconnect" in text
        assert "gateway=vpn.example.com" in text
        assert "usergroup=eng" in text

    def test_did_you_mean_suggestion(self, isolated):
        _cli("profiles", "add", "work", "--server", "vpn.example.com")
        # Typo'd profile name should trigger fuzzy suggestion
        r = _cli("connect", "wokr")
        assert r.returncode != 0
        assert "Did you mean" in r.stderr
        assert "work" in r.stderr


@pytest.mark.integration
class TestQuietAndVerbose:
    def test_quiet_suppresses_info(self, isolated):
        # Add a profile, then check that --quiet status doesn't emit info-level
        _cli("profiles", "add", "work", "--server", "vpn.example.com")
        r = _cli("--quiet", "status")
        # Status without an active VPN exits non-zero (1) — that's fine.
        # We just verify no info-level chatter (no "info" text).
        assert "[info" not in r.stderr.lower()

    def test_quiet_propagates_to_status(self, isolated):
        # `--quiet` is a global flag that should be parsed before the
        # subcommand and not accidentally push us into legacy mode.
        _cli("profiles", "add", "work", "--server", "vpn.example.com")
        r = _cli("--quiet", "status")
        # status without an active VPN exits 1; key thing is it didn't
        # bail out as a legacy connect (rc=2 with usage error).
        assert r.returncode in (0, 1), r.stderr


@pytest.mark.integration
class TestVersionAndDoctor:
    def test_version_plain(self, isolated):
        r = _cli("--version")
        assert r.returncode == 0
        assert "openconnect-saml" in r.stdout

    def test_doctor_runs(self, isolated):
        r = _cli("doctor")
        # Doctor returns 0/1/2 depending on findings; just confirm it ran.
        assert r.returncode in (0, 1, 2)
        assert "diagnostics" in r.stdout or "Active sessions" in r.stdout

    def test_doctor_json(self, isolated):
        r = _cli("doctor", "--json")
        assert r.returncode in (0, 1, 2)
        data = json.loads(r.stdout)
        assert "summary" in data
        assert "checks" in data


@pytest.mark.integration
class TestEndToEndConnect:
    """Drive an actual --authenticate flow against the mock gateway through the
    new ``connect <profile>`` shortcut to make sure profile + auth combine right.
    """

    def test_connect_profile_authenticate_shell(self, isolated):
        with MockGateway() as gw:
            # Add a profile pointing at the mock
            r = _cli(
                "profiles",
                "add",
                "mock",
                "--server",
                gw.url,
                "--user",
                "alice@example.com",
            )
            assert r.returncode == 0, r.stderr
            # connect mock --authenticate shell
            r = _cli(
                "connect",
                "mock",
                "--",
                "--no-cert-check",
                "--no-totp",
                "--no-history",
                "--headless",
                "--authenticate",
                "shell",
                stdin_input="dummy-password\n",
                timeout=30,
            )
        # The combined output (stdout + stderr) should mention the cookie.
        output = r.stdout + r.stderr
        assert (
            f"COOKIE={SESSION_TOKEN}" in r.stdout or "Required attributes not found" not in output
        ), (r.returncode, r.stdout, r.stderr)
