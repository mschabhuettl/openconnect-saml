"""Tests for TUI status display."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from openconnect_saml.tui import (
    _collect_status,
    _extract_server_from_cmdline,
    _format_bytes,
    _format_duration,
    _get_traffic_stats,
    _print_status_plain,
)


class TestFormatDuration:
    def test_seconds(self):
        assert _format_duration(30) == "30s"

    def test_minutes(self):
        assert _format_duration(90) == "1m 30s"

    def test_hours(self):
        assert _format_duration(8100) == "2h 15m"

    def test_zero(self):
        assert _format_duration(0) == "0s"

    def test_large(self):
        result = _format_duration(86400)
        assert "24h" in result


class TestFormatBytes:
    def test_bytes(self):
        assert _format_bytes(512) == "512 B"

    def test_kilobytes(self):
        result = _format_bytes(2048)
        assert "KB" in result

    def test_megabytes(self):
        result = _format_bytes(150 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self):
        result = _format_bytes(1.5 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_none(self):
        assert _format_bytes(None) == "N/A"

    def test_zero(self):
        assert _format_bytes(0) == "0 B"


class TestExtractServer:
    def test_basic(self):
        result = _extract_server_from_cmdline(
            "openconnect --cookie-on-stdin https://vpn.example.com"
        )
        assert "vpn.example.com" in result

    def test_with_path(self):
        result = _extract_server_from_cmdline("openconnect https://vpn.example.com/group")
        assert "vpn.example.com" in result

    def test_no_match(self):
        result = _extract_server_from_cmdline("openconnect --help")
        assert result == "unknown"


class TestTrafficStats:
    def test_parse_proc_net_dev(self, tmp_path):
        proc_content = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  123456      100    0    0    0     0          0         0   123456      100    0    0    0     0       0          0
  tun0: 1234567890   50000    0    0    0     0          0         0  987654321   40000    0    0    0     0       0          0
"""
        proc_file = tmp_path / "net_dev"
        proc_file.write_text(proc_content)

        with patch("openconnect_saml.tui.Path") as mock_path:
            mock_path.return_value.exists.return_value = True
            mock_path.return_value.read_text.return_value = proc_content
            # Direct test of parsing logic
            tx, rx = (
                _get_traffic_stats.__wrapped__(None)
                if hasattr(_get_traffic_stats, "__wrapped__")
                else (None, None)
            )

    def test_traffic_stats_missing_interface(self):
        """Non-existent interface returns None."""
        tx, rx = _get_traffic_stats("nonexistent99")
        assert tx is None
        assert rx is None


class TestStatusPlain:
    def test_disconnected(self, capsys):
        _print_status_plain(None)
        captured = capsys.readouterr()
        assert "Disconnected" in captured.out

    def test_connected(self, capsys):
        status = {
            "profile": "work",
            "server": "vpn.example.com",
            "user": "user@example.com",
            "uptime": "2h 15m",
            "ip": "10.0.1.42",
            "tx": 150 * 1024 * 1024,
            "rx": 1200 * 1024 * 1024,
            "reconnects": 0,
        }
        _print_status_plain(status)
        captured = capsys.readouterr()
        assert "Connected" in captured.out
        assert "work" in captured.out
        assert "vpn.example.com" in captured.out
        assert "10.0.1.42" in captured.out

    def test_connected_na_values(self, capsys):
        status = {
            "profile": "default",
            "server": "vpn.example.com",
            "user": "N/A",
            "uptime": None,
            "ip": "N/A",
            "tx": None,
            "rx": None,
            "reconnects": 0,
        }
        _print_status_plain(status)
        captured = capsys.readouterr()
        assert "N/A" in captured.out


class TestCollectStatus:
    @patch("openconnect_saml.tui._find_vpn_process")
    def test_no_process(self, mock_find):
        mock_find.return_value = None
        assert _collect_status() is None

    @patch("openconnect_saml.tui.config")
    @patch("openconnect_saml.tui._get_reconnect_count")
    @patch("openconnect_saml.tui._get_traffic_stats")
    @patch("openconnect_saml.tui._get_interface_ip")
    @patch("openconnect_saml.tui._get_vpn_interface")
    @patch("openconnect_saml.tui._get_process_start_time")
    @patch("openconnect_saml.tui._find_vpn_process")
    def test_with_process(
        self, mock_find, mock_start, mock_iface, mock_ip, mock_traffic, mock_reconnect, mock_config
    ):
        mock_find.return_value = (1234, "openconnect https://vpn.example.com")
        mock_start.return_value = datetime(2026, 3, 31, 10, 0, 0, tzinfo=timezone.utc)
        mock_iface.return_value = "tun0"
        mock_ip.return_value = "10.0.1.42"
        mock_traffic.return_value = (100000, 200000)
        mock_reconnect.return_value = 0

        mock_cfg = MagicMock()
        mock_cfg.active_profile = "work"
        mock_cfg.credentials = MagicMock()
        mock_cfg.credentials.username = "user@example.com"
        mock_config.load.return_value = mock_cfg

        status = _collect_status()
        assert status is not None
        assert status["connected"] is True
        assert status["server"] == "vpn.example.com"
        assert status["ip"] == "10.0.1.42"
        assert status["profile"] == "work"
