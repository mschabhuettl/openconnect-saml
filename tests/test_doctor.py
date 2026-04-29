"""Tests for the doctor diagnostic command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from openconnect_saml import doctor


class TestCheckResult:
    def test_symbol_ok(self):
        cr = doctor.CheckResult(name="x", status=doctor.STATUS_OK)
        assert cr.symbol == "✓"

    def test_symbol_warn(self):
        cr = doctor.CheckResult(name="x", status=doctor.STATUS_WARN)
        assert cr.symbol == "!"

    def test_symbol_fail(self):
        cr = doctor.CheckResult(name="x", status=doctor.STATUS_FAIL)
        assert cr.symbol == "✗"

    def test_symbol_skip(self):
        cr = doctor.CheckResult(name="x", status=doctor.STATUS_SKIP)
        assert cr.symbol == "~"


class TestPythonVersion:
    def test_current_python_is_ok(self):
        r = doctor._check_python_version()
        assert r.status == doctor.STATUS_OK


class TestOpenconnect:
    def test_missing_openconnect(self):
        with patch("openconnect_saml.doctor.shutil.which", return_value=None):
            r = doctor._check_openconnect()
            assert r.status == doctor.STATUS_FAIL
            assert "not found" in r.message.lower()

    def test_found_openconnect(self):
        fake_result = MagicMock()
        fake_result.stdout = "OpenConnect version v9.10\n"
        fake_result.stderr = ""
        fake_result.returncode = 0
        with patch("openconnect_saml.doctor.shutil.which", return_value="/usr/bin/openconnect"), \
                patch("openconnect_saml.doctor.subprocess.run", return_value=fake_result):
            r = doctor._check_openconnect()
            assert r.status == doctor.STATUS_OK


class TestSudoCheck:
    def test_sudo_available(self):
        with patch("openconnect_saml.doctor.shutil.which",
                   side_effect=lambda x: "/usr/bin/sudo" if x == "sudo" else None):
            r = doctor._check_sudo()
            assert r.status == doctor.STATUS_OK

    def test_doas_preferred_over_sudo(self):
        with patch("openconnect_saml.doctor.shutil.which",
                   side_effect=lambda x: "/usr/bin/doas" if x in ("doas", "sudo") else None):
            r = doctor._check_sudo()
            assert r.status == doctor.STATUS_OK
            assert "doas" in r.message

    def test_windows_is_skipped(self):
        with patch("openconnect_saml.doctor.shutil.which", return_value=None), \
                patch("openconnect_saml.doctor.platform.system", return_value="Windows"):
            r = doctor._check_sudo()
            assert r.status == doctor.STATUS_SKIP

    def test_missing_both_on_linux_is_warn(self):
        with patch("openconnect_saml.doctor.shutil.which", return_value=None), \
                patch("openconnect_saml.doctor.platform.system", return_value="Linux"):
            r = doctor._check_sudo()
            assert r.status == doctor.STATUS_WARN


class TestPythonDeps:
    def test_all_core_deps_present(self):
        results = doctor._check_python_deps()
        # Every entry should have a valid status
        for r in results:
            assert r.status in (doctor.STATUS_OK, doctor.STATUS_FAIL)

    def test_missing_dep_reports_fail(self):
        def fake_import(name):
            if name == "attrs":
                raise ImportError(f"no module named {name}")
            import importlib as _il
            return _il.import_module(name)

        with patch("openconnect_saml.doctor.importlib.import_module",
                   side_effect=fake_import):
            results = doctor._check_python_deps()
            attrs_check = next(r for r in results if "attrs" in r.name)
            assert attrs_check.status == doctor.STATUS_FAIL


class TestDNSResolution:
    def test_no_server_skipped(self):
        r = doctor._check_dns_resolution(None)
        assert r.status == doctor.STATUS_SKIP

    def test_successful_resolution(self):
        fake_info = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("openconnect_saml.doctor.socket.getaddrinfo", return_value=fake_info):
            r = doctor._check_dns_resolution("example.com")
            assert r.status == doctor.STATUS_OK
            assert "93.184.216.34" in r.message

    def test_failure(self):
        import socket
        with patch("openconnect_saml.doctor.socket.getaddrinfo",
                   side_effect=socket.gaierror("nope")):
            r = doctor._check_dns_resolution("does-not-exist.invalid")
            assert r.status == doctor.STATUS_FAIL


class TestServerReachable:
    def test_no_server_skipped(self):
        r = doctor._check_server_reachable(None)
        assert r.status == doctor.STATUS_SKIP

    def test_uses_url_port(self):
        with patch("openconnect_saml.doctor.socket.create_connection",
                   return_value=MagicMock()):
            r = doctor._check_server_reachable("https://vpn.example.com:8443")
            assert r.status == doctor.STATUS_OK
            assert "8443" in r.name


class TestKillSwitchState:
    def test_linux_only_check(self):
        with patch("openconnect_saml.doctor.platform.system", return_value="Darwin"):
            r = doctor._check_killswitch_state()
            assert r.status == doctor.STATUS_SKIP

    def test_no_iptables(self):
        with patch("openconnect_saml.doctor.platform.system", return_value="Linux"), \
                patch("openconnect_saml.doctor.shutil.which", return_value=None):
            r = doctor._check_killswitch_state()
            assert r.status == doctor.STATUS_SKIP


class TestHandleDoctor:
    def test_run_returns_int(self, capsys):
        class Args:
            server = None

        rc = doctor.handle_doctor_command(Args())
        assert rc in (0, 1, 2)
        captured = capsys.readouterr()
        assert "openconnect-saml diagnostics" in captured.out
        assert "Summary:" in captured.out

    def test_exit_code_on_fails(self, capsys):
        # If openconnect is missing, we expect exit 1
        with patch("openconnect_saml.doctor._check_openconnect") as mock_oc:
            mock_oc.return_value = doctor.CheckResult(
                "openconnect binary", doctor.STATUS_FAIL, "not found"
            )

            class Args:
                server = None

            rc = doctor.handle_doctor_command(Args())
            assert rc == 1
