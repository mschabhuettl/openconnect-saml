"""Tests for systemd service management."""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from openconnect_saml.service import (
    UNIT_PREFIX,
    _find_executable,
    _unit_name,
    generate_unit,
    handle_service_command,
)


class TestUnitName:
    def test_simple_server(self):
        name = _unit_name("vpn.example.com")
        assert name == f"{UNIT_PREFIX}@vpn.example.com.service"

    def test_server_with_https(self):
        name = _unit_name("https://vpn.example.com")
        assert name == f"{UNIT_PREFIX}@vpn.example.com.service"

    def test_server_with_path(self):
        name = _unit_name("vpn.example.com/usergroup")
        assert name == f"{UNIT_PREFIX}@vpn.example.com-usergroup.service"

    def test_server_with_port(self):
        name = _unit_name("vpn.example.com:8443")
        assert name == f"{UNIT_PREFIX}@vpn.example.com-8443.service"


class TestGenerateUnit:
    def test_basic_unit(self):
        unit = generate_unit("vpn.example.com")
        assert "[Unit]" in unit
        assert "[Service]" in unit
        assert "[Install]" in unit
        assert "vpn.example.com" in unit
        assert "--headless" in unit
        assert "--reconnect" in unit
        assert "Restart=on-failure" in unit
        assert "RestartSec=30" in unit

    def test_unit_with_user(self):
        unit = generate_unit("vpn.example.com", user="user@domain.com")
        assert "--user" in unit
        assert "user@domain.com" in unit

    def test_unit_with_chrome_browser(self):
        unit = generate_unit("vpn.example.com", browser="chrome")
        assert "--browser chrome" in unit
        assert "--headless" not in unit

    def test_unit_with_max_retries(self):
        unit = generate_unit("vpn.example.com", max_retries=5)
        assert "--max-retries 5" in unit

    def test_unit_with_unlimited_retries(self):
        unit = generate_unit("vpn.example.com", max_retries=None)
        assert "--max-retries" not in unit

    def test_unit_has_network_dependency(self):
        unit = generate_unit("vpn.example.com")
        assert "After=network-online.target" in unit
        assert "Wants=network-online.target" in unit

    def test_unit_has_watchdog(self):
        unit = generate_unit("vpn.example.com")
        assert "WatchdogSec=300" in unit

    def test_unit_multi_user_target(self):
        unit = generate_unit("vpn.example.com")
        assert "WantedBy=multi-user.target" in unit


class TestFindExecutable:
    @patch("shutil.which", return_value="/usr/local/bin/openconnect-saml")
    def test_finds_in_path(self, mock_which):
        result = _find_executable()
        assert result == "/usr/local/bin/openconnect-saml"

    @patch("shutil.which", return_value=None)
    def test_fallback_to_python(self, mock_which):
        result = _find_executable()
        assert "openconnect_saml.cli" in result


class TestInstall:
    @patch("subprocess.run")
    @patch("pathlib.Path.write_text")
    @patch("pathlib.Path.chmod")
    def test_install_creates_unit(self, mock_chmod, mock_write, mock_run):
        from openconnect_saml.service import install

        mock_run.return_value = MagicMock(returncode=0)

        result = install("vpn.example.com", user="user@domain.com")
        assert result == 0
        mock_write.assert_called_once()
        written_content = mock_write.call_args[0][0]
        assert "vpn.example.com" in written_content
        assert "--user" in written_content

    @patch("subprocess.run")
    @patch("pathlib.Path.write_text", side_effect=PermissionError("denied"))
    def test_install_permission_error(self, mock_write, mock_run):
        from openconnect_saml.service import install

        result = install("vpn.example.com")
        assert result == 1


class TestUninstall:
    @patch("subprocess.run")
    @patch("pathlib.Path.exists", return_value=True)
    @patch("pathlib.Path.unlink")
    def test_uninstall_removes_unit(self, mock_unlink, mock_exists, mock_run):
        from openconnect_saml.service import uninstall

        mock_run.return_value = MagicMock(returncode=0)

        result = uninstall("vpn.example.com")
        assert result == 0
        mock_unlink.assert_called_once()

    @patch("pathlib.Path.exists", return_value=False)
    def test_uninstall_nonexistent(self, mock_exists):
        from openconnect_saml.service import uninstall

        result = uninstall("vpn.example.com")
        assert result == 1


class TestHandleServiceCommand:
    def _make_args(self, **kwargs):
        defaults = {
            "service_action": "status",
            "server": None,
            "user": None,
            "browser": "headless",
            "max_retries": None,
            "follow": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("openconnect_saml.service.status", return_value=0)
    def test_status_command(self, mock_status):
        args = self._make_args(service_action="status")
        result = handle_service_command(args)
        assert result == 0

    @patch("openconnect_saml.service.install", return_value=0)
    def test_install_command(self, mock_install):
        args = self._make_args(service_action="install", server="vpn.example.com")
        result = handle_service_command(args)
        assert result == 0
        mock_install.assert_called_once()

    def test_install_without_server(self):
        args = self._make_args(service_action="install", server=None)
        result = handle_service_command(args)
        assert result == 1

    @patch("openconnect_saml.service.logs", return_value=0)
    def test_logs_command(self, mock_logs):
        args = self._make_args(service_action="logs", follow=True)
        result = handle_service_command(args)
        assert result == 0
        mock_logs.assert_called_once_with(server=None, follow=True)
