"""Tests for split-tunnel routing feature."""

from unittest.mock import MagicMock, patch

from openconnect_saml.config import ProfileConfig


class TestProfileRoutes:
    def test_profile_with_routes(self):
        prof = ProfileConfig(
            server="vpn.example.com",
            routes=["10.0.0.0/8", "172.16.0.0/12"],
            no_routes=["192.168.0.0/16"],
        )
        assert prof.routes == ["10.0.0.0/8", "172.16.0.0/12"]
        assert prof.no_routes == ["192.168.0.0/16"]

    def test_profile_no_routes_default(self):
        prof = ProfileConfig(server="vpn.example.com")
        assert prof.routes == []
        assert prof.no_routes == []

    def test_profile_routes_serialization(self):
        prof = ProfileConfig(
            server="vpn.example.com",
            routes=["10.0.0.0/8"],
            no_routes=["192.168.0.0/16"],
        )
        d = prof.as_dict()
        assert d["routes"] == ["10.0.0.0/8"]
        assert d["no_routes"] == ["192.168.0.0/16"]

    def test_profile_routes_from_dict(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "routes": ["10.0.0.0/8"],
                "no_routes": ["192.168.0.0/16"],
            }
        )
        assert prof.routes == ["10.0.0.0/8"]
        assert prof.no_routes == ["192.168.0.0/16"]

    def test_profile_routes_none_default(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
            }
        )
        assert prof.routes == []
        assert prof.no_routes == []


class TestRoutesCLI:
    def test_route_args_parsed(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(
            [
                "connect",
                "--server",
                "vpn.example.com",
                "--route",
                "10.0.0.0/8",
                "--route",
                "172.16.0.0/12",
                "--no-route",
                "192.168.0.0/16",
            ]
        )
        assert args.routes == ["10.0.0.0/8", "172.16.0.0/12"]
        assert args.no_routes == ["192.168.0.0/16"]

    def test_no_route_args_default(self):
        from openconnect_saml.cli import create_argparser

        parser = create_argparser()
        args = parser.parse_args(["connect", "--server", "vpn.example.com"])
        assert args.routes is None
        assert args.no_routes is None


class TestRunOpenconnectRoutes:
    @patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo")
    @patch("openconnect_saml.app.subprocess.run")
    def test_routes_passed_to_openconnect(self, mock_run, mock_which):
        from openconnect_saml.app import run_openconnect

        mock_run.return_value = MagicMock(returncode=0)
        auth_info = MagicMock()
        auth_info.session_token = "test-cookie"
        auth_info.server_cert_hash = "sha256:abc"
        host = MagicMock()
        host.vpn_url = "https://vpn.example.com"

        run_openconnect(
            auth_info,
            host,
            None,
            "4.7.00136",
            [],
            routes=["10.0.0.0/8", "172.16.0.0/12"],
            no_routes=["192.168.0.0/16"],
        )

        cmd = mock_run.call_args[0][0]
        # Check routes are in the command (may be separate args or joined string on Windows)
        cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        assert "--route" in cmd_str
        assert "10.0.0.0/8" in cmd_str
        assert "172.16.0.0/12" in cmd_str
        assert "--no-route" in cmd_str
        assert "192.168.0.0/16" in cmd_str

    @patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo")
    @patch("openconnect_saml.app.subprocess.run")
    def test_no_routes_omitted(self, mock_run, mock_which):
        from openconnect_saml.app import run_openconnect

        mock_run.return_value = MagicMock(returncode=0)
        auth_info = MagicMock()
        auth_info.session_token = "test-cookie"
        auth_info.server_cert_hash = "sha256:abc"
        host = MagicMock()
        host.vpn_url = "https://vpn.example.com"

        run_openconnect(auth_info, host, None, "4.7.00136", [])

        cmd = mock_run.call_args[0][0]
        assert "--route" not in cmd
        assert "--no-route" not in cmd
