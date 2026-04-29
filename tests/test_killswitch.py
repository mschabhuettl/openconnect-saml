"""Tests for the iptables kill-switch."""

from __future__ import annotations

import platform
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from openconnect_saml.killswitch import (
    KillSwitch,
    KillSwitchConfig,
    KillSwitchError,
    KillSwitchNotSupported,
    _is_ipv6,
    _resolve_server_ips,
    handle_killswitch_command,
)


def _mk(returncode=0, stdout="", stderr=""):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


class TestHelpers:
    def test_is_ipv6(self):
        assert _is_ipv6("2001:db8::1") is True
        assert _is_ipv6("1.2.3.4") is False
        assert _is_ipv6("not-an-ip") is False

    def test_resolve_server_ips_valid(self):
        fake_info = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("openconnect_saml.killswitch.socket.getaddrinfo", return_value=fake_info):
            ips = _resolve_server_ips("example.com")
            assert ips == ["93.184.216.34"]

    def test_resolve_server_ips_url(self):
        fake_info = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("openconnect_saml.killswitch.socket.getaddrinfo", return_value=fake_info):
            ips = _resolve_server_ips("https://example.com/usergroup")
            assert ips == ["93.184.216.34"]

    def test_resolve_server_ips_failure(self):
        import socket

        with (
            patch(
                "openconnect_saml.killswitch.socket.getaddrinfo",
                side_effect=socket.gaierror("bad host"),
            ),
            pytest.raises(KillSwitchError),
        ):
            _resolve_server_ips("does-not-exist.invalid")


class TestPlatformCheck:
    def test_not_supported_on_windows(self):
        with patch("openconnect_saml.killswitch.platform.system", return_value="Windows"):
            ks = KillSwitch(KillSwitchConfig())
            with pytest.raises(KillSwitchNotSupported):
                ks.is_active()

    def test_supported_on_darwin_via_pf(self):
        """macOS uses the pf backend; is_active should not raise."""
        with (
            patch("openconnect_saml.killswitch.platform.system", return_value="Darwin"),
            patch(
                "openconnect_saml.killswitch.subprocess.run",
                return_value=_mk(0, "", ""),
            ),
        ):
            ks = KillSwitch(KillSwitchConfig(sudo=""))
            # No rules → not active, but also not raising
            assert ks.is_active() is False


@pytest.mark.skipif(platform.system() != "Linux", reason="Linux only")
class TestKillSwitchLinux:
    def test_not_active_when_chain_missing(self):
        with (
            patch(
                "openconnect_saml.killswitch.subprocess.run",
                return_value=_mk(1, "", "No chain/target/match"),
            ),
            patch("openconnect_saml.killswitch.shutil.which", return_value="/sbin/iptables"),
        ):
            ks = KillSwitch(KillSwitchConfig(sudo=""))
            assert ks.is_active() is False

    def test_active_when_chain_present(self):
        with (
            patch("openconnect_saml.killswitch.subprocess.run", return_value=_mk(0, "", "")),
            patch("openconnect_saml.killswitch.shutil.which", return_value="/sbin/iptables"),
        ):
            ks = KillSwitch(KillSwitchConfig(sudo=""))
            assert ks.is_active() is True

    def test_disable_is_idempotent(self):
        with (
            patch(
                "openconnect_saml.killswitch.subprocess.run", return_value=_mk(1, "", "")
            ) as mock_run,
            patch("openconnect_saml.killswitch.shutil.which", return_value="/sbin/iptables"),
        ):
            ks = KillSwitch(KillSwitchConfig(sudo="", ipv6=False))
            ks.disable(silent=True)
            assert mock_run.called

    def test_enable_requires_server_resolution(self):
        fake_info = [(2, 1, 6, "", ("10.0.0.1", 0))]
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            # -nL to list chain: return 1 (not exists) first time, then OK
            if "-nL" in cmd:
                return _mk(1, "", "No chain")
            return _mk(0, "", "")

        with (
            patch("openconnect_saml.killswitch.socket.getaddrinfo", return_value=fake_info),
            patch("openconnect_saml.killswitch.subprocess.run", side_effect=fake_run),
            patch(
                "openconnect_saml.killswitch.shutil.which",
                side_effect=lambda x: "/sbin/iptables" if x == "iptables" else None,
            ),
        ):
            ks = KillSwitch(
                KillSwitchConfig(
                    server_host="vpn.example.com",
                    sudo="",
                    ipv6=False,
                )
            )
            ks.enable()
            # Check that at least one rule was added with the resolved IP
            added = [c for c in calls if "-A" in c and "10.0.0.1" in c]
            assert added, f"No rule was added with the server IP; calls: {calls}"


class TestKillSwitchCLI:
    def test_enable_requires_server(self, capsys):
        class Args:
            killswitch_action = "enable"
            server = None

        with (
            patch("openconnect_saml.killswitch.platform.system", return_value="Linux"),
            patch("openconnect_saml.killswitch.shutil.which", return_value="/sbin/iptables"),
        ):
            rc = handle_killswitch_command(Args())
            assert rc == 1
            captured = capsys.readouterr()
            assert "--server" in captured.out

    def test_status_not_supported(self, capsys):
        class Args:
            killswitch_action = "status"
            server = None

        with patch("openconnect_saml.killswitch.platform.system", return_value="Windows"):
            rc = handle_killswitch_command(Args())
            assert rc == 2
            captured = capsys.readouterr()
            assert "only supported on linux" in captured.out.lower()


class TestPfBackend:
    """Tests for the macOS pf-based kill-switch backend."""

    def test_render_rules_minimal(self):
        with patch("openconnect_saml.killswitch.platform.system", return_value="Darwin"):
            ks = KillSwitch(KillSwitchConfig(sudo=""))
            rules = ks._pf_render_rules(server_ips=[])
        # Always-present anchors
        assert "set skip on lo0" in rules
        assert "block return-icmp out all" in rules
        assert "pass out quick on utun0" in rules

    def test_render_rules_with_server_and_dns(self):
        cfg = KillSwitchConfig(
            server_host="vpn.example.com",
            dns_servers=["1.1.1.1", "9.9.9.9"],
            sudo="",
        )
        with patch("openconnect_saml.killswitch.platform.system", return_value="Darwin"):
            ks = KillSwitch(cfg)
            rules = ks._pf_render_rules(server_ips=["203.0.113.42"])
        assert "to 203.0.113.42 port 443" in rules
        assert "to 1.1.1.1 port 53" in rules
        assert "to 9.9.9.9 port 53" in rules

    def test_render_rules_with_lan(self):
        cfg = KillSwitchConfig(allow_lan=True, sudo="")
        with patch("openconnect_saml.killswitch.platform.system", return_value="Darwin"):
            ks = KillSwitch(cfg)
            rules = ks._pf_render_rules(server_ips=[])
        assert "to 10.0.0.0/8" in rules
        assert "to 192.168.0.0/16" in rules

    def test_status_reports_pf_backend(self):
        with (
            patch("openconnect_saml.killswitch.platform.system", return_value="Darwin"),
            patch(
                "openconnect_saml.killswitch.subprocess.run",
                return_value=_mk(0, "", ""),
            ),
        ):
            ks = KillSwitch(KillSwitchConfig(sudo=""))
            state = ks.status()
        assert state["backend"] == "pf"
        assert state["active"] is False
        assert state["anchor"] == "openconnect-saml-killswitch"
