# ANALYSIS — autonomous hardening pass (2026-05-26)

Baseline on entry (`main` @ 4fbfce1, v0.24.5):

- `make test`: **947 passed, 4 skipped**, Linux coverage **76.16 %** (floor 73).
- `make lint`: clean (`ruff check` + `ruff format --check`).
- Python in dev box: 3.14.4 (project targets 3.10–3.13; CI matrix covers those + Windows 3.12).

## Open PRs

| PR | Title | CI | Decision |
|----|-------|----|----------|
| #49 | `actions/checkout` 4→6 | all green incl. windows-latest 3.12 | merge |
| #50 | `actions/upload-artifact` 4→6 | all green incl. windows-latest 3.12 | merge |

## Open issues

### #24 — Hardware token does not work in qt-mode
- **Slot-signature crash** (`@pyqtSlot(object)` rejected by PyQt6 6.11 for
  `webAuthUxRequested(QWebEngineWebAuthUxRequest*)`) — **already fixed in v0.21.0**;
  decorator removed, `webengine_process.py:325-336` carries the regression note.
- **Remaining**: PyPI `PyQt6-WebEngine` strips WebUSB at compile time → FIDO2 keys
  cannot be driven in qt-mode on PyPI builds. This is a Qt build limitation, not a
  wrapper bug. Maintainer documented it and steered FIDO2 users to `--browser chrome`.
- **Actionable remainder**: the maintainer promised a `--chrome-executable PATH`
  flag so users with a system `chromium` (no `chrome`, and `--chrome-channel chromium`
  is unsupported by Playwright) can drive FIDO2 via chrome-mode without the 150 MB
  Playwright Chromium download. → covered by Phase 2.

### #39 — playwright not found via AUR / `--browser chrome` not usable
- Wrong-package confusion (`aur/playwright` Node vs `aur/python-playwright`) — error
  message already improved in v0.24.3.
- Real unsolved ask: user has system `chromium`, `--chrome-channel chromium` is not a
  valid Playwright channel, default mode downloads its own Chromium. The promised
  `--chrome-executable PATH` (Playwright `executable_path=`) is the fix. → Phase 2.

## Module-level observations (coverage gaps + risks)

- `app.py` 45 %, `authenticator.py` 59 %, `fido2_auth.py` 59 %, `service.py` 64 %,
  `killswitch.py` 66 % — lowest-covered; many gaps are genuinely platform-specific.
- Cross-platform fragility to verify (CLAUDE.md hot-list): `pgrep`/`ip`/`iptables`/
  `pfctl` callers must catch `FileNotFoundError`; POSIX-only modules (`termios`, `tty`,
  `fcntl`, `pwd`, `grp`, `pty`) lazy/guarded; signals (`SIGUSR1`/`SIGKILL`) guarded;
  `/proc`, `/etc`, `/var/run` wrapped; `os.chmod(0o600)` tests skipped on Windows.
- Test-suite warnings to clean: `datetime.utcnow()` deprecation in
  `tests/integration/mock_saml_gateway.py`; un-awaited coroutine + structlog warning in
  chrome/config tests.

## Orphaned branches (Phase 6 candidates, verify merged first)

- `origin/chore/screenshots-25447672277`
- `origin/claude/analyze-project-i5gvf`
- merged dependabot branches once #49/#50 land.
