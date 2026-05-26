"""Tests for interactive_tui — import safety and entrypoint guards.

interactive_tui.py is excluded from coverage measurement (it requires a real
terminal), but the POSIX-guard logic and the friendly Windows error message
are fully testable via unit tests.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import-safety: module must load without termios/tty present
# ---------------------------------------------------------------------------


class TestModuleImportSafety:
    """Verify that the module can be imported on platforms without termios/tty."""

    def test_module_imports_without_termios(self):
        """Simulated Windows: import succeeds even when termios & tty are absent."""
        mod_name = "openconnect_saml.interactive_tui"

        # Remove the already-imported module from the cache so we get a fresh import.
        saved = sys.modules.pop(mod_name, None)
        try:
            # Pretend termios and tty don't exist (Windows scenario).
            with patch.dict(sys.modules, {"termios": None, "tty": None}):
                imported = importlib.import_module(mod_name)
                assert imported._HAS_POSIX_TTY is False
        finally:
            # Restore the original module (with real termios) for later tests.
            if saved is not None:
                sys.modules[mod_name] = saved
            else:
                sys.modules.pop(mod_name, None)
                importlib.import_module(mod_name)


# ---------------------------------------------------------------------------
# Entrypoint guard: friendly message when POSIX TTY support is absent
# ---------------------------------------------------------------------------


class TestRunPosixGuard:
    """InteractiveTUI.run() must print a clear, actionable message on non-POSIX."""

    def _make_tui(self):
        """Return an InteractiveTUI instance with config stubbed out."""
        from openconnect_saml import interactive_tui

        mock_cfg = MagicMock()
        mock_cfg.list_profiles.return_value = []
        with patch("openconnect_saml.interactive_tui.config.load", return_value=mock_cfg):
            return interactive_tui.InteractiveTUI()

    def test_run_returns_1_when_no_posix_tty(self, capsys):
        """run() exits with rc=1 and prints a helpful message when _HAS_POSIX_TTY is False."""
        import openconnect_saml.interactive_tui as m

        tui = self._make_tui()
        with patch.object(m, "_HAS_POSIX_TTY", False):
            rc = tui.run()

        assert rc == 1
        captured = capsys.readouterr()
        assert "POSIX terminal" in captured.err
        assert "status" in captured.err  # points user to the alternative

    def test_run_posix_error_mentions_watch_flag(self, capsys):
        """The POSIX-unavailable error message must mention --watch/--json alternatives."""
        import openconnect_saml.interactive_tui as m

        tui = self._make_tui()
        with patch.object(m, "_HAS_POSIX_TTY", False):
            tui.run()

        err = capsys.readouterr().err
        assert "--watch" in err or "--json" in err

    def test_run_posix_check_happens_before_rich_check(self, capsys):
        """The POSIX guard must fire even when rich is also absent."""
        import openconnect_saml.interactive_tui as m

        tui = self._make_tui()
        with (
            patch.object(m, "_HAS_POSIX_TTY", False),
            patch.object(m, "_has_rich", return_value=False),
        ):
            rc = tui.run()

        assert rc == 1
        err = capsys.readouterr().err
        # Should mention POSIX, NOT the rich install hint
        assert "POSIX terminal" in err
        assert "openconnect-saml[tui]" not in err
