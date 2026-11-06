"""Confirm the exit-code assumption with the installed OpenConnect binary."""

import base64
import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from openconnect_saml import app, config, sessions, token_cache
from openconnect_saml.authenticator import AuthCompleteResponse
from tests.integration.mock_saml_gateway import MockGateway, _Handler


def gateway_pin(gateway):
    cert = x509.load_pem_x509_certificate(gateway._cert_path.read_bytes())
    digest = hashes.Hash(hashes.SHA256())
    digest.update(
        cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    return "pin-sha256:" + base64.b64encode(digest.finalize()).decode()


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("openconnect") is None, reason="OpenConnect binary unavailable")
@pytest.mark.parametrize("detach", [False, True])
def test_real_openconnect_rejects_saved_cookie_and_refreshes_once(monkeypatch, tmp_path, detach):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    vault = {}
    monkeypatch.setattr(token_cache.keyring, "get_password", lambda s, k: vault.get((s, k)))
    monkeypatch.setattr(
        token_cache.keyring, "set_password", lambda s, k, v: vault.__setitem__((s, k), v)
    )
    monkeypatch.setattr(
        token_cache.keyring, "delete_password", lambda s, k: vault.pop((s, k), None)
    )
    sent = []

    def reject_cookie(handler):
        sent.append(handler.headers.get("Cookie"))
        handler.send_response(401)
        handler.send_header("Content-Length", "0")
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True

    monkeypatch.setattr(_Handler, "do_CONNECT", reject_cookie, raising=False)
    monkeypatch.setattr(_Handler, "protocol_version", "HTTP/1.1")
    with MockGateway(host="127.0.0.1") as gateway:
        # OpenConnect pins the public key, rather than the certificate DER.
        pin = gateway_pin(gateway)
        host = config.HostProfile(gateway.url, "", "")
        cached = AuthCompleteResponse("success", "", "saved-cookie", pin)
        fresh = AuthCompleteResponse("success", "", "fresh-cookie", pin)
        options = SimpleNamespace(
            proxy=None,
            ac_version="4.7.00136",
            openconnect_args=[],
            _using_cached_token=True,
            _token_cache_key="key",
        )
        token_cache.save("key", cached, host)
        with (
            patch.object(app, "_run", AsyncMock(return_value=(fresh, host))) as refresh,
            patch.object(app.config, "save"),
        ):
            result = app._connect_with_token_refresh(
                options, config.Config(), cached, host, no_sudo=True, on_pid=None, detach=detach
            )
    assert result == 2
    assert sent == ["webvpn=saved-cookie", "webvpn=fresh-cookie"]
    refresh.assert_awaited_once()
    assert token_cache.load("key") is None


@pytest.mark.integration
@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("openconnect"), reason="POSIX OpenConnect required"
)
@pytest.mark.parametrize("detach", [False, True])
def test_real_tunnel_reuses_cookie_after_disconnect_and_refreshes_after_logout(
    tmp_path, monkeypatch, detach
):
    """Use real CSTP and script-tun; no kernel tunnel or routing changes."""
    cookies, revoked, logouts = [], set(), []

    def serve_tunnel(handler):
        cookie = handler.headers.get("Cookie")
        cookies.append(cookie)
        if cookie in revoked:
            handler.send_response(401)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            handler.close_connection = True
            return
        handler.send_response(200, "CONNECTED")
        for key, value in {
            "Address": "192.0.2.2",
            "Netmask": "255.255.255.0",
            "MTU": "1406",
        }.items():
            handler.send_header("X-CSTP-" + key, value)
        handler.end_headers()
        handler.wfile.flush()
        handler.connection.settimeout(10)
        data = b""
        while True:
            chunk = handler.connection.recv(4096)
            if not chunk:
                break
            data += chunk
            while len(data) >= 8:
                length = int.from_bytes(data[4:6], "big") + 8
                if len(data) < length:
                    break
                assert data[:4] == b"STF\x01"
                if data[6] == 5:  # CSTP BYE logs the server session out.
                    logouts.append(cookie)
                    revoked.add(cookie)
                data = data[length:]
        handler.close_connection = True

    monkeypatch.setattr(_Handler, "do_CONNECT", serve_tunnel, raising=False)
    monkeypatch.setattr(_Handler, "protocol_version", "HTTP/1.1")
    program = textwrap.dedent("""\
        import json, sys
        from pathlib import Path
        from openconnect_saml import app, config, token_cache
        from openconnect_saml.authenticator import AuthCompleteResponse
        from openconnect_saml.cli import create_argparser
        url, pin, vault, count, script, detach = sys.argv[1:]
        vault, count = Path(vault), Path(count)
        def entries():
            return json.loads(vault.read_text()) if vault.exists() else {}
        def save(service, key, value):
            data = entries()
            data[key] = value
            vault.write_text(json.dumps(data))
        def delete(service, key):
            data = entries()
            data.pop(key, None)
            vault.write_text(json.dumps(data))
        token_cache.keyring.get_password = lambda service, key: entries().get(key)
        token_cache.keyring.set_password = save
        token_cache.keyring.delete_password = delete
        async def login(*args, **kwargs):
            n = int(count.read_text()) + 1 if count.exists() else 1
            count.write_text(str(n))
            return AuthCompleteResponse("success", "", "cookie-" + str(n), pin)
        app.authenticate_to = login
        app.config.load = lambda: config.Config(
            credentials={"username": "alice"}, username_only=True, connection_history=False,
        )
        app.config.save = lambda cfg: None
        options = create_argparser().parse_args(["connect", "--server", url, "--no-sudo"])
        options.openconnect_args = ["--no-dtls", "--script-tun", "--script", script]
        options.detach = detach == "True"
        raise SystemExit(app.run(options))
    """)
    environment = {**os.environ, "XDG_STATE_HOME": str(tmp_path / "state")}
    with MockGateway(host="127.0.0.1") as gateway:
        pin = gateway_pin(gateway)
        for cycle, action in enumerate(("ctrl-c", "disconnect", "logout", "ctrl-c")):
            ready = tmp_path / f"ready-{cycle}"
            script = shlex.join(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os; from pathlib import Path; "
                        f"Path({str(ready)!r}).touch(); "
                        "os.read(int(os.environ['VPNFD']), 1)"
                    ),
                ]
            )
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    program,
                    gateway.url,
                    pin,
                    str(tmp_path / "vault"),
                    str(tmp_path / "logins"),
                    script,
                    str(detach),
                ],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            stop = None
            try:
                deadline = time.monotonic() + 10
                while (
                    not ready.exists()
                    and (proc.poll() is None or (detach and proc.returncode == 0))
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                if not ready.exists():
                    proc.terminate()
                    output, _ = proc.communicate(timeout=20)
                    pytest.fail(output.decode(errors="replace"))
                if detach:
                    output, _ = proc.communicate(timeout=20)
                    assert proc.returncode == 0, output.decode(errors="replace")
                if action == "ctrl-c" and not detach:
                    proc.send_signal(signal.SIGINT)
                else:
                    stop = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "openconnect_saml.cli",
                            "disconnect",
                            "default",
                            *(["--logout"] if action == "logout" else []),
                        ],
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                    )
                if not detach:
                    output, _ = proc.communicate(timeout=20)
                    assert proc.returncode == 0, output.decode(errors="replace")
                if stop:
                    stopped, _ = stop.communicate(timeout=5)
                    assert stop.returncode == 0, stopped.decode(errors="replace")
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    proc.communicate(timeout=20)
                if stop is not None and stop.poll() is None:
                    stop.kill()
                    stop.wait(timeout=2)
                if detach:
                    with patch.dict(os.environ, {"XDG_STATE_HOME": str(tmp_path / "state")}):
                        if sessions.load("default"):
                            sessions.kill("default", timeout=2)
    assert cookies == ["webvpn=cookie-1"] * 4 + ["webvpn=cookie-2"]
    assert logouts == ["webvpn=cookie-1"]
    assert (tmp_path / "logins").read_text() == "2"


@pytest.mark.integration
@pytest.mark.skipif(
    os.name != "posix" or not shutil.which("openconnect"), reason="POSIX OpenConnect required"
)
@pytest.mark.parametrize("privilege", ["none", "self", "root"])
@pytest.mark.parametrize("reject", [False, True])
def test_native_detach_reports_startup_result_and_tracks_background_pid(
    tmp_path, monkeypatch, privilege, reject
):
    """A real background tunnel survives its launcher; failed startup has no PID."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    prefix = []
    if privilege != "none":
        sudo = shutil.which("sudo")
        if not sudo or os.getuid() == 0:
            pytest.skip("Requires sudo and an unprivileged test runner")
        prefix = [sudo, "-n"]
        if privilege == "self":
            prefix.extend(["-u", f"#{os.getuid()}"])
        if subprocess.run([*prefix, "true"], capture_output=True, timeout=5).returncode:
            pytest.skip("Existing sudo authorization unavailable")
        popen = subprocess.Popen

        def elevated(command, **options):
            if command[0] == "sudo":
                assert command[1] == "-p"
                command = [*prefix, *command[3:]]
            return popen(command, **options)

        monkeypatch.setattr(app.subprocess, "Popen", elevated)
        which = shutil.which
        monkeypatch.setattr(
            app.shutil, "which", lambda name: None if name == "doas" else which(name)
        )
    closed = threading.Event()
    connected = threading.Event()

    def connect(handler):
        if reject:
            handler.send_response(401)
            handler.send_header("Content-Length", "0")
            handler.end_headers()
        else:
            handler.send_response(200, "CONNECTED")
            for key, value in {
                "Address": "192.0.2.2",
                "Netmask": "255.255.255.0",
                "MTU": "1406",
            }.items():
                handler.send_header("X-CSTP-" + key, value)
            handler.end_headers()
            handler.wfile.flush()
            connected.set()
            handler.connection.settimeout(10)
            while handler.connection.recv(4096):
                pass
            closed.set()
        handler.close_connection = True

    monkeypatch.setattr(_Handler, "do_CONNECT", connect, raising=False)
    monkeypatch.setattr(_Handler, "protocol_version", "HTTP/1.1")
    ready = tmp_path / "ready"
    script = shlex.join(
        [
            sys.executable,
            "-c",
            (
                "import os; from pathlib import Path; "
                f"Path({str(ready)!r}).touch(); os.read(int(os.environ['VPNFD']), 1)"
            ),
        ]
    )
    options = SimpleNamespace(
        profile_name="test",
        user=None,
        proxy=None,
        ac_version="version",
        openconnect_args=["--no-dtls", "--script-tun", "--script", script],
    )
    try:
        with MockGateway(host="127.0.0.1") as gateway:
            result = app._connect_with_token_refresh(
                options,
                config.Config(),
                AuthCompleteResponse("success", "", "test-cookie", gateway_pin(gateway)),
                config.HostProfile(gateway.url, "", ""),
                detach=True,
                no_sudo=privilege == "none",
                wait_seconds=5,
            )
            if reject:
                assert result == 2
                assert sessions.load("test") is None
            else:
                assert result == 0
                record = sessions.load("test")
                assert record is not None
                assert record.pid != os.getpid()
                assert record.elevation == ("" if privilege == "none" else "sudo")
                deadline = time.monotonic() + 2
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                assert connected.is_set() and ready.exists()
                assert not closed.is_set()
                assert sessions.kill("test", timeout=3)
                assert closed.wait(timeout=3)
    finally:
        with contextlib.suppress(OSError):
            if sessions.load("test"):
                sessions.kill("test", timeout=0)
