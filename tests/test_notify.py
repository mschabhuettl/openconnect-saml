"""Tests for desktop notifications."""

from unittest.mock import MagicMock, patch

from openconnect_saml.notify import (
    NotificationLevel,
    _notify_bell,
    _notify_linux,
    _notify_macos,
    notify_connected,
    notify_disconnected,
    notify_error,
    notify_reconnecting,
    send_notification,
)


class TestNotifyLinux:
    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/notify-send")
    @patch("openconnect_saml.notify.subprocess.run")
    def test_sends_notification(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_linux("Test", "Hello")
        assert result is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert args[0] == "/usr/bin/notify-send"
        assert "Test" in args
        assert "Hello" in args

    @patch("openconnect_saml.notify.shutil.which", return_value=None)
    def test_no_notify_send(self, mock_which):
        result = _notify_linux("Test", "Hello")
        assert result is False

    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/notify-send")
    @patch("openconnect_saml.notify.subprocess.run", side_effect=FileNotFoundError)
    def test_handles_error(self, mock_run, mock_which):
        result = _notify_linux("Test", "Hello")
        assert result is False

    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/notify-send")
    @patch("openconnect_saml.notify.subprocess.run")
    def test_error_urgency(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        _notify_linux("Error", "Fail", NotificationLevel.ERROR)
        args = mock_run.call_args[0][0]
        assert "--urgency=critical" in args


class TestNotifyMacOS:
    @patch("openconnect_saml.notify.shutil.which", return_value="/usr/bin/osascript")
    @patch("openconnect_saml.notify.subprocess.run")
    def test_sends_notification(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0)
        result = _notify_macos("Test", "Hello")
        assert result is True
        mock_run.assert_called_once()

    @patch("openconnect_saml.notify.shutil.which", return_value=None)
    def test_no_osascript(self, mock_which):
        result = _notify_macos("Test", "Hello")
        assert result is False


class TestNotifyBell:
    def test_always_returns_true(self, capsys):
        result = _notify_bell("Test", "Hello")
        assert result is True
        captured = capsys.readouterr()
        assert "Test" in captured.out
        assert "Hello" in captured.out


class TestSendNotification:
    @patch("openconnect_saml.notify.platform.system", return_value="Linux")
    @patch("openconnect_saml.notify._notify_linux", return_value=True)
    def test_linux_dispatch(self, mock_linux, mock_sys):
        result = send_notification("Test", "Hello")
        assert result is True
        mock_linux.assert_called_once()

    @patch("openconnect_saml.notify.platform.system", return_value="Darwin")
    @patch("openconnect_saml.notify._notify_macos", return_value=True)
    def test_macos_dispatch(self, mock_macos, mock_sys):
        result = send_notification("Test", "Hello")
        assert result is True
        mock_macos.assert_called_once()

    @patch("openconnect_saml.notify.platform.system", return_value="Windows")
    def test_fallback_to_bell(self, mock_sys, capsys):
        result = send_notification("Test", "Hello")
        assert result is True

    @patch("openconnect_saml.notify.platform.system", return_value="Linux")
    @patch("openconnect_saml.notify._notify_linux", return_value=False)
    def test_linux_fallback(self, mock_linux, mock_sys, capsys):
        result = send_notification("Test", "Hello")
        assert result is True  # Falls back to bell


class TestNotifyHelpers:
    @patch("openconnect_saml.notify.send_notification")
    def test_notify_connected(self, mock_send):
        notify_connected("vpn.example.com", "work")
        mock_send.assert_called_once()
        title, msg = mock_send.call_args[0][:2]
        assert "Connected" in title
        assert "vpn.example.com" in msg
        assert "work" in msg

    @patch("openconnect_saml.notify.send_notification")
    def test_notify_disconnected(self, mock_send):
        notify_disconnected("vpn.example.com")
        mock_send.assert_called_once()
        title = mock_send.call_args[0][0]
        assert "Disconnected" in title

    @patch("openconnect_saml.notify.send_notification")
    def test_notify_reconnecting(self, mock_send):
        notify_reconnecting("vpn.example.com", 3, 120)
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "120s" in msg
        assert "#3" in msg

    @patch("openconnect_saml.notify.send_notification")
    def test_notify_error(self, mock_send):
        notify_error("vpn.example.com", "auth failed")
        mock_send.assert_called_once()
        title = mock_send.call_args[0][0]
        assert "Error" in title
