# UX Findings — issues outside the ux/diagnostics-polish scope

Observed during the diagnostics/setup-wizard/tui polish pass (2026-05-26).

## Out-of-scope issues for follow-up

### 1. `status` — "Connected" field label ambiguity  (`tui.py`)
The rich/plain status output previously used "Connected" as the label for
the uptime duration (e.g. "Connected: 2h 15m"). This is confusing — the
heading line already says "Connected". **Fixed in this PR** (renamed to
"Uptime"). No other places need changing.

### 2. `app.py` — missing `FileNotFoundError` handling for `openconnect` binary
`app.py:run_openconnect()` calls `subprocess.run()` / `subprocess.Popen()` with
the `openconnect` binary but does not catch `FileNotFoundError`. If the binary
disappears between the `doctor` check and the `connect` run, the user sees a
raw Python traceback. The fix is to wrap those calls in a try/except and
return a dedicated exit code (20 has been proposed). A test file
`tests/test_app_openconnect_spawn.py` exists on the `fix/openconnect-missing-binary`
branch that covers this but the corresponding `app.py` change has not been
merged yet.

### 3. `interactive_tui.py` — POSIX-only top-level imports ✅ FIXED
`interactive_tui.py` previously imported `termios` and `tty` at the module level.
**Fixed in this PR** (commit `d9948d0`): both imports are now wrapped in a
`try/except ImportError` block with a `_HAS_POSIX_TTY` sentinel; `run()` checks
the sentinel first and prints a clear, actionable error message on non-POSIX
platforms. Four new tests in `tests/test_interactive_tui.py` cover import safety
and the Windows-friendly error path.

### 4. `setup_wizard.py` — no URL validation for VPN server
The wizard accepts any string as the VPN server URL. A user who types
`"https://vpn.example.com"` (with scheme) now gets the scheme stripped (fixed
in this PR), but a user who types `"not a hostname at all"` will get a confusing
error later at connection time rather than a clear validation failure during setup.
A lightweight DNS lookup check (similar to `doctor._check_dns_resolution`) in the
wizard would improve first-run success rate.

### 5. `doctor.py` — `_check_env_hygiene` reports OK when credentials ARE present
The current implementation returns `STATUS_OK` when credential env vars are found
("N credential env var(s) present") — but the name "hygiene" suggests a warning
would be more appropriate. This is a minor UX inconsistency; changing the status
to `STATUS_WARN` could affect existing tooling that checks exit codes.
