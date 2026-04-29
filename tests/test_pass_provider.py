"""Tests for the pass (password-store) TOTP provider."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from openconnect_saml.totp_providers import PassProvider


def _mk_result(returncode=0, stdout="", stderr=""):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


class TestPassProvider:
    def test_no_pass_binary(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value=None):
            p = PassProvider(entry="vpn/work")
            assert p.get_totp() is None

    def test_successful_totp(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/pass"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(0, "654321\n")) as mock_run:
            p = PassProvider(entry="vpn/work")
            assert p.get_totp() == "654321"
            cmd = mock_run.call_args.args[0]
            assert cmd == ["/usr/bin/pass", "otp", "vpn/work"]

    def test_entry_not_found(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/pass"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(1, "", "Error: vpn/missing is not in the password store.")):
            p = PassProvider(entry="vpn/missing")
            assert p.get_totp() is None

    def test_pass_otp_not_installed(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/pass"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(1, "",
                                              "Error: otp command not found. Usage: ...")):
            p = PassProvider(entry="vpn/work")
            assert p.get_totp() is None

    def test_no_otp_secret(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/pass"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(1, "", "Error: No OTP secret found in vpn/work")):
            p = PassProvider(entry="vpn/work")
            assert p.get_totp() is None

    def test_gpg_timeout(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/pass"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      side_effect=subprocess.TimeoutExpired(cmd="pass", timeout=15)):
            p = PassProvider(entry="vpn/work")
            assert p.get_totp() is None

    def test_empty_stdout(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/pass"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(0, "", "")):
            p = PassProvider(entry="vpn/work")
            assert p.get_totp() is None
