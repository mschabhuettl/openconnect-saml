"""Tests for run_openconnect() degrading cleanly when the VPN binary is absent.

Spawning a missing ``openconnect`` binary raises FileNotFoundError; the
wrapper must turn that into a clear message + exit code 20 rather than an
unhandled traceback. Mirrors the FileNotFoundError handling already present
in handle_connect / handle_disconnect / handle_error.
"""

from unittest.mock import MagicMock, patch


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
