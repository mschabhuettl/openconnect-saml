import platform
import shlex
import sys
from unittest.mock import MagicMock, patch

import pytest

from openconnect_saml.app import run_openconnect
from openconnect_saml.config import HostProfile


@patch("subprocess.run")
@patch("os.name", "nt")
def test_run_openconnect_windows(mock_run):
    auth_info = MagicMock()
    auth_info.session_token = "session_token"
    auth_info.server_cert_hash = "server_cert_hash"
    host = HostProfile("server", "group", "name")
    proxy = None
    version = "4.7.00136"
    args = []

    # Mock ctypes.windll for non-Windows platforms
    mock_ctypes = MagicMock()
    mock_ctypes.windll.shell32.IsUserAnAdmin.return_value = True
    with patch.dict(sys.modules, {"ctypes": mock_ctypes}):
        run_openconnect(auth_info, host, proxy, version, args)

    openconnect_args = [
        "openconnect",
        "--useragent",
        f"AnyConnect Win {version}",
        "--version-string",
        version,
        "--cookie-on-stdin",
        "--servercert",
        auth_info.server_cert_hash,
        *args,
        host.vpn_url,
    ]
    expected_command = ["powershell.exe", "-Command", shlex.join(openconnect_args)]
    mock_run.assert_called_once_with(expected_command, input=b"session_token")


@patch("subprocess.run")
@patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo")
@pytest.mark.skipif(platform.system() == "Windows", reason="Linux-specific test")
def test_run_openconnect_linux_with_sudo(mock_which, mock_run):
    """Test normal Linux execution with sudo."""
    auth_info = MagicMock()
    auth_info.session_token = "session_token"
    auth_info.server_cert_hash = "server_cert_hash"
    host = HostProfile("server", "group", "name")

    run_openconnect(auth_info, host, None, "4.7.00136", [])

    cmd = mock_run.call_args[0][0]
    # First found superuser tool (doas checked before sudo, but we mocked which to always return)
    assert cmd[0] in ("sudo", "doas")
    assert "openconnect" in cmd


@patch("subprocess.run")
@pytest.mark.skipif(platform.system() == "Windows", reason="Linux-specific test")
def test_run_openconnect_linux_no_sudo(mock_run):
    """Test --no-sudo flag skips privilege escalation."""
    auth_info = MagicMock()
    auth_info.session_token = "session_token"
    auth_info.server_cert_hash = "server_cert_hash"
    host = HostProfile("server", "group", "name")

    run_openconnect(auth_info, host, None, "4.7.00136", [], no_sudo=True)

    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "openconnect"


@patch("subprocess.run")
@pytest.mark.skipif(platform.system() == "Windows", reason="Linux-specific test")
def test_run_openconnect_with_csd_wrapper(mock_run):
    """Test --csd-wrapper passthrough."""
    auth_info = MagicMock()
    auth_info.session_token = "session_token"
    auth_info.server_cert_hash = "server_cert_hash"
    host = HostProfile("server", "group", "name")

    run_openconnect(
        auth_info, host, None, "4.7.00136", [], no_sudo=True, csd_wrapper="/path/to/csd.sh"
    )

    cmd = mock_run.call_args[0][0]
    assert "--csd-wrapper" in cmd
    assert "/path/to/csd.sh" in cmd
