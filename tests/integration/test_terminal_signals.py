"""Real terminal shutdown with a harmless client, optionally via installed sudo."""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from openconnect_saml import sessions

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires POSIX terminals")


@pytest.mark.parametrize(
    "privilege, reuse",
    [
        ("none", False),
        ("self", False),
        ("none", True),
        ("self", True),
        ("root", True),
    ],
)
@pytest.mark.parametrize("action", ["ctrl-c", "disconnect", "logout"])
def test_terminal_shutdown(tmp_path, monkeypatch, privilege, reuse, action):
    import pty
    import select

    run_as_self = []
    if privilege != "none":
        sudo = shutil.which("sudo")
        if not sudo or os.getuid() == 0:
            pytest.skip("Requires sudo and an unprivileged test runner")
        run_as_self = [sudo, "-n"]
        if privilege == "self":
            run_as_self.extend(["-u", f"#{os.getuid()}"])
        probe = subprocess.run([*run_as_self, "true"], capture_output=True, timeout=10)
        if probe.returncode:
            pytest.skip(f"sudo cannot run as {privilege} without a password")

    ready, received, cleaned, tracked = (
        tmp_path / name for name in ("ready", "received", "cleaned", "tracked")
    )
    client_program = textwrap.dedent("""\
        import json, os, signal, sys, time
        from pathlib import Path
        ready, received, cleaned = map(Path, sys.argv[1:])
        def stop(sig, frame):
            received.write_text(signal.Signals(sig).name)
            time.sleep(0.1)  # Simulate graceful network cleanup.
            cleaned.write_text("done")
            raise SystemExit(0)
        signal.signal(signal.SIGINT, stop)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGHUP, stop)
        cookie = sys.stdin.read()
        ready.write_text(json.dumps({"pid": os.getpid(), "uid": os.getuid(), "cookie": cookie}))
        while True:
            time.sleep(0.1)
    """)
    parent_program = textwrap.dedent("""\
        import fcntl, json, sys, termios
        from pathlib import Path
        from types import SimpleNamespace
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        from openconnect_saml import app, config
        prefix = json.loads(sys.argv[1])
        reuse = sys.argv[2] == "True"
        client, ready, received, cleaned, tracked = sys.argv[3:]
        original_popen = app.subprocess.Popen
        def launch(command, **kwargs):
            # Replace only the VPN binary with a harmless client. Keep the
            # actual Popen flags, sudo monitor, terminal, and stdin behavior.
            assert "--cookie-on-stdin" in command
            if prefix:
                assert command[:2] == ["sudo", "-p"]
                command = [*prefix, *command[3:]]
            index = command.index("openconnect")
            return original_popen([
                *command[:index], sys.executable, "-c", client, ready, received, cleaned
            ], **kwargs)
        app.subprocess.Popen = launch
        app.shutil.which = lambda name: "sudo" if name == "sudo" else None
        try:
            rc = app.run_openconnect(
                SimpleNamespace(session_token="test-cookie", server_cert_hash="pin"),
                config.HostProfile("vpn.invalid", "", ""), None, "version", [],
                no_sudo=not prefix, on_pid=lambda pid: Path(tracked).write_text(str(pid)),
                reuse_session=reuse,
            )
        except KeyboardInterrupt:
            rc = 0
        raise SystemExit(rc)
    """)
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            parent_program,
            json.dumps(run_as_self),
            str(reuse),
            client_program,
            str(ready),
            str(received),
            str(cleaned),
            str(tracked),
        ],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        start_new_session=True,
    )
    os.close(slave)
    child = None
    disconnect = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "test client did not start"
        child = json.loads(ready.read_text())
        assert child["cookie"] == "test-cookie"
        assert child["uid"] == (0 if privilege == "root" else os.getuid())
        if action == "ctrl-c":
            # Exercise the terminal driver, not a synthetic killpg(SIGINT).
            os.write(master, b"\x03")
        else:
            monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
            sessions.record(
                sessions.Session(
                    profile="test",
                    server="vpn.invalid",
                    pid=int(tracked.read_text()),
                    controlled=reuse,
                )
            )
            disconnect = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "openconnect_saml.cli",
                    "disconnect",
                    "test",
                    *(["--logout"] if action == "logout" else []),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        # Drain terminal output as a terminal emulator would. In particular,
        # sudo may wait for its output relay before reporting command exit.
        output = bytearray()
        deadline = time.monotonic() + 10
        while (
            proc.poll() is None or (disconnect is not None and disconnect.poll() is None)
        ) and time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                with contextlib.suppress(OSError):
                    output.extend(os.read(master, 65536))
        assert proc.poll() is not None, output.decode(errors="replace")
        assert proc.returncode == 0
        if disconnect is not None:
            stdout, stderr = disconnect.communicate(timeout=2)
            assert disconnect.returncode == 0, (stdout, stderr)
        deadline = time.monotonic() + 5
        while not cleaned.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        expected = (
            "SIGHUP"
            if reuse and action != "logout"
            else ("SIGINT" if action == "ctrl-c" else "SIGTERM")
        )
        assert received.read_text() == expected
        assert cleaned.read_text() == "done"
    finally:
        if disconnect is not None and disconnect.poll() is None:
            disconnect.kill()
            disconnect.wait(timeout=2)
        if child and not cleaned.exists():
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(child["pid"], signal.SIGKILL)
        os.close(master)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


@pytest.mark.parametrize("payload", [b"disconnect\n", b""])
def test_unresponsive_tunnel_is_cleaned_up_on_request_or_controller_exit(tmp_path, payload):
    """A stuck child cannot turn disconnect or a crashed controller into a hang."""
    ready = tmp_path / "ready"
    client = textwrap.dedent("""\
        import os, signal, sys, time
        from pathlib import Path
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        sys.stdin.read()
        Path(sys.argv[1]).write_text(str(os.getpid()))
        while True: time.sleep(0.1)
    """)
    helper = """
import sys
from openconnect_saml import tunnel
tunnel.STOP_TIMEOUT = tunnel.TERM_TIMEOUT = 0.2
raise SystemExit(tunnel._serve(sys.argv[1:]))
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", helper, sys.executable, "-c", client, str(ready)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    child = None
    try:
        proc.stdin.write(b'"test-cookie"\n')
        proc.stdin.flush()
        deadline = time.monotonic() + 5
        while not ready.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        child = int(ready.read_text())
        started = time.monotonic()
        stdout, stderr = proc.communicate(input=payload, timeout=3)
        assert proc.returncode == 1, (stdout, stderr)
        assert b"forcing process cleanup" in stderr
        assert time.monotonic() - started < 3
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)
        if child:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child, signal.SIGKILL)
