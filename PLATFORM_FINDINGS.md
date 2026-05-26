# Cross-Platform Findings — Out-of-Scope Files

Files below are **outside** the cross-platform robustness agent's strict ownership
(`killswitch.py`, `service.py`, `headless.py`, `notify.py`) and therefore cannot
be edited directly. They are documented here for the agent that owns each file.

---

## `openconnect_saml/app.py`

### `run_openconnect()` — missing `FileNotFoundError` guard on openconnect spawn

**Lines:** 958, 977, 989, 997

All four execution paths in `run_openconnect()` call `subprocess.Popen` /
`subprocess.run` with `command_line` whose first element is `openconnect` (or
`powershell.exe` on Windows wrapping it). None of the call sites catch
`FileNotFoundError`.

If the `openconnect` binary is not installed — which is normal on Windows and
in CI containers — the function crashes with an unhandled `FileNotFoundError`
instead of returning a meaningful exit code with a user-facing error message.

**Contrast:** `handle_connect()`, `handle_disconnect()`, and `handle_error()` in
the same file already catch `(FileNotFoundError, OSError)` and log cleanly.

**Recommended fix (app.py owner):**

```python
try:
    proc = subprocess.Popen(command_line, **popen_kwargs)  # nosec
except FileNotFoundError:
    logger.error(
        "openconnect binary not found — install openconnect and ensure it is in PATH",
        command=command_line[0],
    )
    return 127
```

Apply the same pattern to the three other call sites.

**Severity:** Medium — causes a confusing traceback instead of a clean error
on any system without openconnect installed (Windows, minimal containers).

---

## `openconnect_saml/interactive_tui.py`

### `termios` and `tty` imported at module level

**Lines:** 17–19

```python
import termios
import tty
```

These POSIX-only modules are imported unconditionally at the top of the file.
On Windows, importing `openconnect_saml.interactive_tui` raises
`ModuleNotFoundError: No module named 'termios'`.

Because `interactive_tui.py` is only reached via `openconnect-saml tui`, this
may be acceptable as a "Linux/macOS only feature", but it would be cleaner to
gate the imports or the entire `tui` subcommand behind
`if sys.platform != "win32"`.

**Recommended fix (interactive_tui.py owner):**

```python
if sys.platform != "win32":
    import termios
    import tty
```

And guard the `termios.tcgetattr` / `tty.setraw` call sites behind
`sys.platform != "win32"`.

**Severity:** Low — only triggered if a Windows user runs `openconnect-saml tui`;
the primary connection flow is unaffected.

---

## `openconnect_saml/tui.py` — already clean ✓

- `pgrep` call at line 24 is already wrapped in
  `except (subprocess.TimeoutExpired, FileNotFoundError, ValueError)`.
- `/proc/<pid>/stat` path at line 45 uses `Path(...).exists()` before reading.
- No bare POSIX-only imports.

---

## Files audited and confirmed clean (owned scope)

| File | Result |
|------|--------|
| `killswitch.py` | Fixed in PR #52 — `_chain_exists()` now catches `FileNotFoundError` |
| `service.py`    | Fixed in PR #52 — `_ensure_systemd_available()` guard on all public functions |
| `headless.py`   | Fixed in PR #52 — `_run_auth_script()` catches `FileNotFoundError` |
| `notify.py`     | Already clean — `shutil.which` + `(FileNotFoundError, OSError)` in all paths |
