"""Tests for the PyPI version-check helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openconnect_saml import version_check as vc


class TestParseVersion:
    def test_basic(self):
        assert vc._parse_version("0.14.0") == (0, 14, 0)

    def test_with_dev(self):
        assert vc._parse_version("0.14.0a1") == (0, 14, 0)

    def test_truncates_garbage(self):
        assert vc._parse_version("garbage") == ()

    def test_compare(self):
        assert vc._parse_version("0.15.0") > vc._parse_version("0.14.0")
        assert vc._parse_version("0.14.10") > vc._parse_version("0.14.2")


class TestCheck:
    def test_returns_outdated_when_remote_newer(self):
        with patch.object(vc, "get_latest_pypi_version", return_value="9.99.99"):
            info = vc.check()
        assert info.is_outdated is True
        assert info.latest == "9.99.99"
        assert "Update with" in (info.hint_line() or "")

    def test_returns_current_when_same(self):
        from openconnect_saml import __version__

        with patch.object(vc, "get_latest_pypi_version", return_value=__version__):
            info = vc.check()
        assert info.is_outdated is False
        assert info.hint_line() is None

    def test_returns_none_latest_on_failure(self):
        with patch.object(vc, "get_latest_pypi_version", return_value=None):
            info = vc.check()
        assert info.latest is None
        assert info.is_outdated is False
        assert info.hint_line() is None


class TestGetLatestFromPypi:
    def test_returns_version_string(self):
        fake_response = MagicMock()
        fake_response.json.return_value = {"info": {"version": "1.2.3"}}
        fake_response.raise_for_status.return_value = None
        with patch("requests.get", return_value=fake_response):
            assert vc.get_latest_pypi_version() == "1.2.3"

    def test_swallows_network_errors(self):
        with patch("requests.get", side_effect=ConnectionError("offline")):
            assert vc.get_latest_pypi_version() is None

    def test_swallows_timeout(self):
        with patch("requests.get", side_effect=TimeoutError("slow")):
            assert vc.get_latest_pypi_version() is None

    def test_returns_none_on_malformed_json(self):
        fake_response = MagicMock()
        fake_response.json.return_value = {"info": {}}
        fake_response.raise_for_status.return_value = None
        with patch("requests.get", return_value=fake_response):
            assert vc.get_latest_pypi_version() is None
