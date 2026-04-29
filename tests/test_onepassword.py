"""Tests for the 1Password TOTP provider."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from openconnect_saml.totp_providers import OnePasswordProvider


def _mk_result(returncode=0, stdout="", stderr=""):
    result = MagicMock(spec=subprocess.CompletedProcess)
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


class TestOnePasswordProvider:
    def test_no_op_binary_returns_none(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value=None):
            provider = OnePasswordProvider(item="my-vpn")
            assert provider.get_totp() is None

    def test_successful_totp(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(0, "123456\n")) as mock_run:
            provider = OnePasswordProvider(item="my-vpn")
            assert provider.get_totp() == "123456"
            args, kwargs = mock_run.call_args
            cmd = args[0]
            assert cmd[0] == "/usr/bin/op"
            assert "item" in cmd and "get" in cmd and "my-vpn" in cmd
            assert "--otp" in cmd

    def test_with_vault_and_account(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(0, "999999\n")) as mock_run:
            provider = OnePasswordProvider(
                item="my-vpn", vault="Work", account="acme.1password.com"
            )
            assert provider.get_totp() == "999999"
            cmd = mock_run.call_args.args[0]
            assert "--vault" in cmd
            assert "Work" in cmd
            assert "--account" in cmd
            assert "acme.1password.com" in cmd

    def test_not_signed_in(self, caplog):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(1, "", "[ERROR] 2023/01/01 00:00:00 not signed in")):
            provider = OnePasswordProvider(item="my-vpn")
            assert provider.get_totp() is None

    def test_no_such_item(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(1, "", "no such item")):
            provider = OnePasswordProvider(item="missing")
            assert provider.get_totp() is None

    def test_no_otp_field(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(1, "",
                                              "this item does not have a one-time password")):
            provider = OnePasswordProvider(item="no-otp")
            assert provider.get_totp() is None

    def test_empty_output_is_treated_as_failure(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      return_value=_mk_result(0, "", "")):
            provider = OnePasswordProvider(item="my-vpn")
            assert provider.get_totp() is None

    def test_timeout(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      side_effect=subprocess.TimeoutExpired(cmd="op", timeout=10)):
            provider = OnePasswordProvider(item="my-vpn")
            assert provider.get_totp() is None

    def test_file_not_found(self):
        with patch("openconnect_saml.totp_providers.shutil.which", return_value="/usr/bin/op"), \
                patch("openconnect_saml.totp_providers.subprocess.run",
                      side_effect=FileNotFoundError("op")):
            provider = OnePasswordProvider(item="my-vpn")
            assert provider.get_totp() is None
