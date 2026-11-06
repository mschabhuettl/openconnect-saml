"""Tests for run_openconnect() degrading cleanly when the VPN binary is absent.

Spawning a missing ``openconnect`` binary raises FileNotFoundError; the
wrapper must turn that into a clear message + exit code 20 rather than an
unhandled traceback. Mirrors the FileNotFoundError handling already present
in handle_connect / handle_disconnect / handle_error.
"""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


def _auth_and_host():
    auth_info = MagicMock()
    auth_info.session_token = "test-cookie"
    auth_info.server_cert_hash = "sha256:abc"
    host = MagicMock()
    host.vpn_url = "https://vpn.example.com"
    return auth_info, host


class TestRunOpenconnectMissingBinary:
    @patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo")
    @patch("openconnect_saml.app.subprocess.run", side_effect=FileNotFoundError("openconnect"))
    def test_plain_path_returns_20_when_binary_missing(self, mock_run, mock_which):
        from openconnect_saml.app import run_openconnect

        auth_info, host = _auth_and_host()
        rc = run_openconnect(auth_info, host, None, "4.7.00136", [])
        assert rc == 20

    @patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo")
    @patch("openconnect_saml.app.subprocess.Popen", side_effect=FileNotFoundError("openconnect"))
    def test_detach_path_returns_20_when_binary_missing(self, mock_popen, mock_which):
        from openconnect_saml.app import run_openconnect

        auth_info, host = _auth_and_host()
        rc = run_openconnect(auth_info, host, None, "4.7.00136", [], detach=True)
        assert rc == 20

    @patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo")
    @patch("openconnect_saml.app.subprocess.run")
    def test_does_not_interfere_with_normal_run(self, mock_run, mock_which):
        """A present binary (mocked subprocess) still returns its real code."""
        from openconnect_saml.app import run_openconnect

        mock_run.return_value = MagicMock(returncode=0)
        auth_info, host = _auth_and_host()
        rc = run_openconnect(auth_info, host, None, "4.7.00136", [])
        assert rc == 0


@pytest.mark.skipif(os.name != "posix", reason="Native background mode is POSIX-only")
@pytest.mark.parametrize(
    "program, expected",
    [
        ("import sys; print('startup failed', file=sys.stderr); sys.exit(7)", 7),
        ("pass", 1),
        ("import time; time.sleep(60)", 1),
    ],
)
def test_detach_does_not_report_success_for_failed_or_incomplete_startup(program, expected):
    from openconnect_saml.app import run_openconnect

    auth, host = _auth_and_host()
    popen = subprocess.Popen

    def launch(command, **options):
        assert "--background" in command
        assert "--pid-file" in command
        return popen([sys.executable, "-c", program], **options)

    record = MagicMock()
    with patch("openconnect_saml.app.subprocess.Popen", side_effect=launch):
        rc = run_openconnect(
            auth,
            host,
            None,
            "version",
            [],
            no_sudo=True,
            detach=True,
            wait_seconds=0.2,
            on_pid=record,
        )
    assert rc == expected
    record.assert_not_called()


@pytest.mark.parametrize("result", [0, 7])
def test_detached_launch_does_not_run_disconnect_hook_on_success(result):
    from unittest.mock import AsyncMock

    from openconnect_saml import app, config
    from openconnect_saml.cli import create_argparser

    auth, host = _auth_and_host()
    cfg = config.Config(connection_history=False, on_disconnect="cleanup")
    args = create_argparser().parse_args(["connect", "--server", "vpn.invalid", "--detach"])
    with (
        patch.object(app.config, "load", return_value=cfg),
        patch.object(app.config, "save"),
        patch.object(app, "configure_logger"),
        patch.object(app, "_run", AsyncMock(return_value=(auth, host))),
        patch.object(app, "run_openconnect", return_value=result),
        patch.object(app, "handle_disconnect") as cleanup,
    ):
        assert app.run(args) == result
    assert cleanup.call_count == (0 if result == 0 else 1)


def test_detached_launch_rejects_temporary_kill_switch():
    from unittest.mock import AsyncMock

    from openconnect_saml import app, config
    from openconnect_saml.cli import create_argparser

    auth, host = _auth_and_host()
    args = create_argparser().parse_args(
        ["connect", "--server", "vpn.invalid", "--detach", "--kill-switch"]
    )
    with (
        patch.object(app.config, "load", return_value=config.Config()),
        patch.object(app.config, "save"),
        patch.object(app, "configure_logger"),
        patch.object(app, "_run", AsyncMock(return_value=(auth, host))),
        patch.object(app, "_setup_killswitch") as firewall,
        patch.object(app, "run_openconnect") as connect,
    ):
        assert app.run(args) == 20
    firewall.assert_not_called()
    connect.assert_not_called()
