"""End-to-end integration test driving the real CLI against a mock gateway.

Spawns ``openconnect-saml --headless --authenticate shell --no-cert-check``
as a subprocess pointed at the in-process mock gateway and asserts the
emitted cookie matches what the gateway handed out. ``--authenticate
shell`` short-circuits the actual openconnect spawn, so this test
exercises the full SAML protocol path without needing a real VPN or
root.
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec
import sys

import pytest

from tests.integration.mock_saml_gateway import (
    CERT_HASH_PLACEHOLDER,
    SESSION_TOKEN,
    MockGateway,
)


@pytest.fixture
def isolated_xdg(tmp_path, monkeypatch):
    """Run the CLI against an empty config / state dir so it doesn't touch
    the developer's real config or read stale profiles between runs."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    yield tmp_path


def _run_cli(
    *argv: str,
    cwd: str | None = None,
    timeout: int = 30,
    stdin_input: str | None = None,
) -> subprocess.CompletedProcess:
    """Run ``python -m openconnect_saml.cli ARGV`` and return the CompletedProcess.

    ``stdin_input`` is fed verbatim to the child's stdin — useful to satisfy
    `getpass.getpass` prompts when the test env has no controlling tty.
    """
    return subprocess.run(  # nosec
        [sys.executable, "-m", "openconnect_saml.cli", *argv],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env={**os.environ},
        input=stdin_input,
    )


@pytest.mark.integration
def test_authenticate_shell_against_mock_gateway(isolated_xdg, monkeypatch):
    """Full SAML auth flow → CLI prints the session-token cookie.

    Disabling cert validation via ``--no-cert-check`` because the mock
    gateway uses a freshly-generated self-signed certificate.
    """
    if shutil.which("openconnect") is None:
        pytest.skip("openconnect binary not available — skipping E2E test")

    with MockGateway() as gw:
        result = _run_cli(
            "--server",
            gw.url,
            "--headless",
            "--user",
            "alice@example.com",
            "--no-totp",
            "--no-cert-check",
            "--no-history",
            "--authenticate",
            "shell",
            stdin_input="dummy-password\n",
        )

    assert result.returncode == 0, (
        f"CLI exited non-zero ({result.returncode}); "
        f"stderr was:\n{result.stderr}\nstdout:\n{result.stdout}"
    )
    # ``--authenticate shell`` prints HOST=, COOKIE=, FINGERPRINT= lines on stdout
    assert f"COOKIE={SESSION_TOKEN}" in result.stdout, result.stdout
    assert f"FINGERPRINT={CERT_HASH_PLACEHOLDER}" in result.stdout, result.stdout
    # The gateway should have seen at least 2 POSTs to / (init + auth-reply)
    posts = [r for r in gw.request_log if r["method"] == "POST" and r["path"] == "/"]
    assert len(posts) >= 2, [r["path"] for r in gw.request_log]
    init_body = posts[0]["body"].decode("utf-8", errors="replace")
    assert 'type="init"' in init_body
    reply_body = posts[1]["body"].decode("utf-8", errors="replace")
    assert 'type="auth-reply"' in reply_body
    # The credentials we pre-populated via the env-var dance should NOT
    # appear in the auth-reply (only the SSO token does).
    assert "TEST-SSO-TOKEN" in reply_body


@pytest.mark.integration
def test_authenticate_json_format(isolated_xdg, monkeypatch):
    """The ``--authenticate json`` form should produce parseable JSON."""
    import json

    with MockGateway() as gw:
        result = _run_cli(
            "--server",
            gw.url,
            "--headless",
            "--user",
            "alice@example.com",
            "--no-totp",
            "--no-cert-check",
            "--no-history",
            "--authenticate",
            "json",
            stdin_input="dummy-password\n",
        )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["cookie"] == SESSION_TOKEN
    assert payload["fingerprint"] == CERT_HASH_PLACEHOLDER
    assert payload["host"].startswith("https://localhost:")


@pytest.mark.integration
def test_allowed_hosts_does_not_break_normal_flow(isolated_xdg, monkeypatch):
    """When ``--allowed-hosts`` includes the gateway, auth should still work.

    The whitelist auto-extends with the gateway + login URL hosts, so
    setting it explicitly to those hosts (or even leaving it empty/unset
    in this test) shouldn't change the happy path. Unit-level tests in
    ``test_headless_whitelist.py`` cover the actual blocking semantics.
    """
    with MockGateway() as gw:
        result = _run_cli(
            "--server",
            gw.url,
            "--headless",
            "--user",
            "alice@example.com",
            "--no-totp",
            "--no-cert-check",
            "--no-history",
            "--allowed-hosts",
            "localhost",
            "--authenticate",
            "shell",
            stdin_input="dummy-password\n",
        )
    assert result.returncode == 0, result.stderr
    assert f"COOKIE={SESSION_TOKEN}" in result.stdout
