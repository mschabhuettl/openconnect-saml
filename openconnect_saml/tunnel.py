"""Own a POSIX tunnel and disconnect it without logging its session out.

The helper runs under the same privilege elevation as OpenConnect. OpenConnect
gets its own terminal session; sudo and the helper remain in the foreground
so the password prompt and terminal relay keep working. Control and the cookie use
stdin, never command-line arguments or a file.
"""

import contextlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

STOP_TIMEOUT = 10
TERM_TIMEOUT = 5


def run(command, cookie, *, elevation=(), on_pid=None, on_connect=None):
    """Run a supervised tunnel, keeping all terminal signals off OpenConnect."""
    request = None

    def stop(signum, _frame):
        nonlocal request
        if signum == signal.SIGUSR1:
            request = b"logout\n"
        elif request is None:
            request = b"disconnect\n"

    previous = {
        sig: signal.signal(sig, stop)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGUSR1)
    }
    proc = None
    deadline = None
    try:
        # Resolve before sudo/doas can replace PATH (e.g. Homebrew installs).
        command = [shutil.which(command[0]) or command[0], *command[1:]]
        proc = subprocess.Popen(  # nosec - command is an argument list, not shell code
            [*elevation, sys.executable, "-I", str(Path(__file__).resolve()), *command],
            stdin=subprocess.PIPE,
        )
        try:
            proc.stdin.write(json.dumps(cookie.decode("utf-8")).encode() + b"\n")
            proc.stdin.flush()
        except BrokenPipeError:
            pass
        if on_pid:
            on_pid(os.getpid())
        if on_connect and request is None:
            on_connect()
        sent = None
        while proc.poll() is None:
            if request is not None and request != sent:
                with contextlib.suppress(BrokenPipeError):
                    proc.stdin.write(request)
                    proc.stdin.flush()
                sent = request
                deadline = deadline or time.monotonic() + STOP_TIMEOUT + TERM_TIMEOUT + 5
            if deadline is not None and time.monotonic() >= deadline:
                print("VPN controller did not exit; stopping it.", file=sys.stderr)
                return 1
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=0.1)
        rc = proc.returncode
        return 0 if request is not None and rc in (130, -signal.SIGINT, -signal.SIGHUP) else rc
    finally:
        try:
            if proc is not None:
                with contextlib.suppress(BrokenPipeError):
                    proc.stdin.close()
                # EOF also asks the helper to clean up if this controller fails.
                remaining = (
                    max(0, deadline - time.monotonic())
                    if deadline is not None
                    else STOP_TIMEOUT + TERM_TIMEOUT + 2
                )
                if proc.poll() is None:
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=remaining)
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    if proc.poll() is None:
                        with contextlib.suppress(ProcessLookupError, PermissionError):
                            proc.send_signal(sig)
                        with contextlib.suppress(subprocess.TimeoutExpired):
                            proc.wait(timeout=2)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)


def _stop_process(proc, *, logout=False):
    with contextlib.suppress(ProcessLookupError):
        proc.send_signal(signal.SIGTERM if logout else signal.SIGHUP)
    try:
        proc.wait(timeout=STOP_TIMEOUT)
        return 0
    except subprocess.TimeoutExpired:
        print("VPN disconnect timed out; forcing logout.", file=sys.stderr)
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        proc.wait(timeout=TERM_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("VPN did not stop; forcing process cleanup.", file=sys.stderr)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=2)
    return 1


def _serve(command):
    """Privileged half: own the child and handle requests from its controller."""
    request = None

    def stop(_signum, _frame):
        nonlocal request
        if request is None:
            request = "disconnect"

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    # Unbuffered input prevents readline from hiding an already-arrived stop
    # request from the selector after it reads the initial cookie.
    control = os.fdopen(0, "rb", buffering=0, closefd=False)
    cookie = json.loads(control.readline()).encode("utf-8")
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, start_new_session=True)  # nosec
    try:
        try:
            proc.stdin.write(cookie)
            proc.stdin.close()
        except BrokenPipeError:
            pass
        with selectors.DefaultSelector() as selector:
            selector.register(control, selectors.EVENT_READ)
            while proc.poll() is None and request is None:
                for _key, _events in selector.select(timeout=0.1):
                    data = os.read(control.fileno(), 4096)
                    if b"logout\n" in data:
                        request = "logout"
                    elif request is None:
                        request = "disconnect"
        return _stop_process(proc, logout=request == "logout") if request else proc.returncode
    finally:
        if proc.poll() is None:
            _stop_process(proc)


if __name__ == "__main__":
    try:
        status = _serve(sys.argv[1:])
    except FileNotFoundError:
        print("OpenConnect executable not found; install it and check your PATH.", file=sys.stderr)
        status = 20
    except (OSError, ValueError):
        print("Could not start the VPN process.", file=sys.stderr)
        status = 20
    raise SystemExit(status)
