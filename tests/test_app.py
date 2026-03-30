import shlex
from unittest.mock import MagicMock, patch

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
