"""Tests for split-tunnel routing feature."""

import sys
from unittest.mock import MagicMock, patch

import pytest

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


def _make_auth_and_host():
    auth_info = MagicMock()
    auth_info.session_token = "test-cookie"
    auth_info.server_cert_hash = "sha256:abc"
    host = MagicMock()
    host.vpn_url = "https://vpn.example.com"
    return auth_info, host


class TestBuildRouteScriptContent:
    """Unit tests for the vpnc-wrapper script generator."""

    def test_include_routes(self):
        from openconnect_saml.app import _build_route_script_content

        content = _build_route_script_content(
            ["10.0.0.0/8", "172.16.0.0/12"], [], "/usr/share/vpnc-scripts/vpnc-script"
        )
        assert "CISCO_SPLIT_INC=2" in content
        assert "CISCO_SPLIT_INC_0_ADDR=10.0.0.0" in content
        assert "CISCO_SPLIT_INC_0_MASK=255.0.0.0" in content
        assert "CISCO_SPLIT_INC_0_MASKLEN=8" in content
        assert "CISCO_SPLIT_INC_1_ADDR=172.16.0.0" in content
        assert "CISCO_SPLIT_INC_1_MASKLEN=12" in content
        assert "CISCO_SPLIT_EXC" not in content
        assert "exec" in content
        assert "/usr/share/vpnc-scripts/vpnc-script" in content

    def test_exclude_routes(self):
        from openconnect_saml.app import _build_route_script_content

        content = _build_route_script_content([], ["192.168.0.0/16"], "/etc/vpnc/vpnc-script")
        assert "CISCO_SPLIT_EXC=1" in content
        assert "CISCO_SPLIT_EXC_0_ADDR=192.168.0.0" in content
        assert "CISCO_SPLIT_EXC_0_MASK=255.255.0.0" in content
        assert "CISCO_SPLIT_EXC_0_MASKLEN=16" in content
        assert "CISCO_SPLIT_INC" not in content

    def test_combined_routes(self):
        from openconnect_saml.app import _build_route_script_content

        content = _build_route_script_content(
            ["10.0.0.0/8"], ["192.168.0.0/16"], "/usr/share/vpnc-scripts/vpnc-script"
        )
        assert "CISCO_SPLIT_INC=1" in content
        assert "CISCO_SPLIT_EXC=1" in content

    def test_exec_line_at_end(self):
        from openconnect_saml.app import _build_route_script_content

        content = _build_route_script_content(
            ["10.0.0.0/8"], [], "/usr/share/vpnc-scripts/vpnc-script"
        )
        last_nonempty = [line for line in content.splitlines() if line.strip()][-1]
        assert last_nonempty.startswith("exec ")

    def test_shebang(self):
        from openconnect_saml.app import _build_route_script_content

        content = _build_route_script_content(
            ["10.0.0.0/8"], [], "/usr/share/vpnc-scripts/vpnc-script"
        )
        assert content.startswith("#!/bin/sh")


@pytest.mark.skipif(sys.platform == "win32", reason="vpnc-script wrapper is POSIX-only")
class TestRunOpenconnectRoutes:
    """run_openconnect() should use a --script wrapper instead of --route/--no-route."""

    def _run(self, routes=None, no_routes=None, extra_args=None, vpnc_path="/fake/vpnc-script"):
        from openconnect_saml.app import run_openconnect

        auth_info, host = _make_auth_and_host()
        written = {}

        def fake_write(content):
            written["content"] = content
            return "/tmp/openconnect-saml-test-wrapper.sh"

        with (
            patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo"),
            patch("openconnect_saml.app.subprocess.run", return_value=MagicMock(returncode=0)),
            patch("openconnect_saml.app._locate_vpnc_script", return_value=vpnc_path),
            patch("openconnect_saml.app._write_route_script", side_effect=fake_write),
        ):
            rc = run_openconnect(
                auth_info,
                host,
                None,
                "4.7.00136",
                extra_args or [],
                routes=routes,
                no_routes=no_routes,
            )
            import openconnect_saml.app as _app

            call = _app.subprocess.run.call_args
            cmd = call[0][0] if call is not None else None
        return rc, cmd, written.get("content")

    def test_script_flag_in_command(self):
        rc, cmd, content = self._run(
            routes=["10.0.0.0/8", "172.16.0.0/12"], no_routes=["192.168.0.0/16"]
        )
        assert rc == 0
        assert "--script" in cmd
        assert "/tmp/openconnect-saml-test-wrapper.sh" in cmd

    def test_no_literal_route_flags(self):
        """The old broken flags must not appear in the openconnect argv."""
        rc, cmd, content = self._run(routes=["10.0.0.0/8"])
        assert "--route" not in cmd
        assert "--no-route" not in cmd

    def test_wrapper_content_includes(self):
        rc, cmd, content = self._run(routes=["10.0.0.0/8", "172.16.0.0/12"])
        assert content is not None
        assert "CISCO_SPLIT_INC=2" in content
        assert "CISCO_SPLIT_INC_0_ADDR=10.0.0.0" in content
        assert "CISCO_SPLIT_INC_1_ADDR=172.16.0.0" in content
        assert "/fake/vpnc-script" in content

    def test_wrapper_content_excludes(self):
        rc, cmd, content = self._run(no_routes=["192.168.0.0/16"])
        assert content is not None
        assert "CISCO_SPLIT_EXC=1" in content
        assert "CISCO_SPLIT_EXC_0_ADDR=192.168.0.0" in content

    def test_no_routes_no_script_flag(self):
        """When no routes are given, --script must NOT be added."""
        from openconnect_saml.app import run_openconnect

        auth_info, host = _make_auth_and_host()
        with (
            patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo"),
            patch("openconnect_saml.app.subprocess.run", return_value=MagicMock(returncode=0)),
        ):
            run_openconnect(auth_info, host, None, "4.7.00136", [])
            import openconnect_saml.app as _app

            cmd = _app.subprocess.run.call_args[0][0]
        assert "--script" not in cmd
        assert "--route" not in cmd
        assert "--no-route" not in cmd

    def test_vpnc_script_not_found_returns_error(self):
        rc, cmd, content = self._run(routes=["10.0.0.0/8"], vpnc_path=None)
        assert rc == 20
        assert content is None

    def test_invalid_cidr_returns_error(self):
        from openconnect_saml.app import run_openconnect

        auth_info, host = _make_auth_and_host()
        with (
            patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo"),
            patch("openconnect_saml.app._locate_vpnc_script", return_value="/fake/vpnc-script"),
        ):
            rc = run_openconnect(auth_info, host, None, "4.7.00136", [], routes=["not-a-cidr"])
        assert rc == 20

    def test_ipv6_cidr_returns_error(self):
        from openconnect_saml.app import run_openconnect

        auth_info, host = _make_auth_and_host()
        with (
            patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo"),
            patch("openconnect_saml.app._locate_vpnc_script", return_value="/fake/vpnc-script"),
        ):
            rc = run_openconnect(auth_info, host, None, "4.7.00136", [], routes=["2001:db8::/32"])
        assert rc == 20

    def test_user_script_conflict_skips_wrapper(self):
        """If user passes --script, routes are ignored and no wrapper is generated."""
        from openconnect_saml.app import run_openconnect

        auth_info, host = _make_auth_and_host()
        written = {}

        def fake_write(content):
            written["content"] = content
            return "/tmp/should-not-be-used.sh"

        with (
            patch("openconnect_saml.app.shutil.which", return_value="/usr/bin/sudo"),
            patch("openconnect_saml.app.subprocess.run", return_value=MagicMock(returncode=0)),
            patch("openconnect_saml.app._locate_vpnc_script", return_value="/fake/vpnc-script"),
            patch("openconnect_saml.app._write_route_script", side_effect=fake_write),
        ):
            rc = run_openconnect(
                auth_info,
                host,
                None,
                "4.7.00136",
                ["--script", "/my/custom-script.sh"],
                routes=["10.0.0.0/8"],
            )
            import openconnect_saml.app as _app

            cmd = _app.subprocess.run.call_args[0][0]
        assert rc == 0
        assert "content" not in written  # wrapper was never written
        # The user's own --script is preserved
        assert "--script" in cmd
        assert "/my/custom-script.sh" in cmd


class TestRunOpenconnectRoutesWindows:
    """On Windows, routes are silently ignored with a warning."""

    def test_windows_routes_ignored(self):
        from openconnect_saml.app import run_openconnect

        auth_info, host = _make_auth_and_host()
        written = {}

        def fake_write(content):
            written["content"] = content
            return "/tmp/should-not-be-used.sh"

        # Simulate Windows: patch os.name and provide a fake ctypes module so
        # the IsUserAnAdmin() check inside run_openconnect() doesn't fail on Linux.
        fake_ctypes = MagicMock()
        fake_ctypes.windll.shell32.IsUserAnAdmin.return_value = True

        with (
            patch("openconnect_saml.app.os.name", "nt"),
            patch.dict(sys.modules, {"ctypes": fake_ctypes}),
            patch("openconnect_saml.app.subprocess.run", return_value=MagicMock(returncode=0)),
            patch("openconnect_saml.app._locate_vpnc_script", return_value="/fake/vpnc-script"),
            patch("openconnect_saml.app._write_route_script", side_effect=fake_write),
        ):
            run_openconnect(
                auth_info,
                host,
                None,
                "4.7.00136",
                [],
                routes=["10.0.0.0/8"],
            )
        assert "content" not in written  # wrapper must not have been written
