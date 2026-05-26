# API/Auth/Config Audit — openconnect-saml

**Agent:** audit/api-coverage  
**Date:** 2026-05-26  
**Scope:** `authenticator.py`, `fido2_auth.py`, `encrypted_backup.py`, `totp_providers.py`,
`profiles.py`, `sessions.py`, `history.py`, `config.py`, `config_cmd.py`

---

## Summary

| Severity | Count | Fixed |
|----------|-------|-------|
| HIGH     | 1     | 0 (out of scope — authenticator.py) |
| MEDIUM   | 3     | 3 |
| LOW      | 4     | 1 |
| INFO     | 3     | 0 |

Coverage moved from 76.16 % → ≥ 78 % after new tests.

---

## Findings

### HIGH

#### SEC-01 — Session token logged at DEBUG level
**File:** `openconnect_saml/authenticator.py:176`  
**Status:** ⚠ Flagged (cannot fix — another agent owns authenticator.py)

```python
logger.debug("Auth finish response received", content=response.content)
```

The complete HTTP response body from the VPN gateway — which includes the
session token returned after a successful SAML assertion — is logged verbatim
at DEBUG level.  Running with `--log-level DEBUG` (common for troubleshooting)
writes the session token to stderr/log files.  An attacker with read access to
a log file could replay the token to connect to the VPN without credentials.

**Recommended fix (for the agent that owns authenticator.py):**  Strip or
truncate the response before logging, or log only the HTTP status code:

```python
logger.debug(
    "Auth finish response received",
    status=response.status_code,
    size=len(response.content),
)
```

Similarly, line 119 (`_start_authentication`) logs the full XML request body
including the VPN URL. This is less sensitive but still more than necessary.

---

### MEDIUM

#### BUG-01 — `config_cmd._cmd_import` writes config without validation
**File:** `openconnect_saml/config_cmd.py:355–361`  
**Status:** ✅ Fixed

```python
# Validate the merged config before writing   ← comment, but no code follows
target_path.parent.mkdir(parents=True, exist_ok=True)
target_path.write_text(toml.dumps(merged))
target_path.chmod(0o600)
```

The comment promises schema validation before persisting the merged config,
but no validation is performed.  An invalid or corrupt imported TOML file could
silently overwrite the user's working config with an unloadable one.

**Fix applied:** Added `config.Config.from_dict(config._rename_toml_to_py(merged))`
before writing. On failure, the function now returns 1 without touching the
existing config.

---

#### SEC-02 — Username not sanitised before writing NM connection file
**File:** `openconnect_saml/profiles.py:658`  
**Status:** ✅ Fixed

```python
lines += [
    "[vpn-secrets]",
    f"form:main:username={username}",  # username unsanitised
    "",
]
```

A profile `credentials.username` containing a newline character could inject
arbitrary INI sections/keys into the generated `.nmconnection` file.  Example:
a username of `"alice\n[connection]\nid=evil"` would silently corrupt the NM
connection metadata.  Profiles come from the user's own config file so this is
a local-privilege / self-XSS concern rather than a remote one, but it can cause
confusing NetworkManager import failures that are hard to diagnose.

**Fix applied:** Strip `\r` and `\n` from `username` and `user_group` before
writing them into the NM file.

---

#### BUG-02 — `history._export_history` silently swallows file-write errors
**File:** `openconnect_saml/history.py:375–377`  
**Status:** ✅ Fixed

```python
if target and target != "-":
    Path(target).write_text(payload)         # OSError not caught
    print(f"✓ Wrote {len(entries)} entries to {target}")
```

`Path.write_text()` raises `OSError` if the destination is unwritable (e.g.
read-only path, non-existent parent directory).  The exception propagates as an
unhandled traceback instead of a clean error message + non-zero exit code.
The same issue exists for the CSV branch.

**Fix applied:** Wrapped both branches in `try/except OSError` with error
message and `return 1`.

---

### LOW

#### SEC-03 — FIDO2 base64 padding: `+ "=="` is fragile for length % 4 == 0 or 1
**File:** `openconnect_saml/fido2_auth.py:250, 256`  
**Status:** ✅ Fixed

```python
challenge = base64.urlsafe_b64decode(challenge_data["challenge"] + "==")
```

`+ "=="` appends exactly two padding characters.  For base64 strings whose
length modulo 4 is 0 or 1 this produces an invalid padded string; Python 3's
`binascii.a2b_base64` is lenient in practice but the standard-conformant
approach is `+ '=' * (-len(s) % 4)`.  WebAuthn servers produce unpadded
base64url strings of any residue class, so all four cases must be handled.

**Fix applied:** Changed to `base64.urlsafe_b64decode(s + '=' * (-len(s) % 4))`
for both `challenge` and the `allowCredentials` id values.

---

#### INFO-01 — `config.save()` redundant double-chmod
**File:** `openconnect_saml/config.py:88–89`  
**Status:** Not fixed (trivial; no correctness impact)

```python
path.touch(mode=0o600)
path.chmod(0o600)
```

`touch(mode=0o600)` already sets the mode; the subsequent `chmod(0o600)` is
redundant.  On systems with a restrictive umask the `touch` call might not
achieve 0o600 without the subsequent `chmod`, so the double-call is harmless
and arguably defensive.  Not changed to avoid noise.

---

#### INFO-02 — `Credentials.password` / `Credentials.totp` return `""` on `KeyringError`
**File:** `openconnect_saml/config.py:223, 283`  
**Status:** Not fixed (design choice; consistent with existing contract)

On `KeyringError` both properties return `""` (empty string) rather than
`None`.  This is consistent throughout the codebase (same behaviour in
`LocalTotpProvider.get_totp()`), but makes it impossible for callers to
distinguish "keyring unavailable" from "credential is an empty string".  A
future cleanup could introduce a `CredentialUnavailable` sentinel and a typed
protocol, but changing it now would require coordinated updates to all callers.

---

#### INFO-03 — Session file briefly world-readable between write and chmod
**File:** `openconnect_saml/sessions.py:104–107`  
**Status:** Not fixed (platform limitation)

```python
path.write_text(json.dumps(...))
with contextlib.suppress(OSError):
    os.chmod(path, 0o600)
```

Between `write_text()` and `chmod()` there is a brief window during which the
file may be readable to other users (depending on `umask`).  The proper fix is
atomic write + rename or opening with `O_CREAT|O_EXCL|O_RDWR` and then
`fchmod`.  Not fixed because (a) the data is non-secret (no credentials), (b)
`_state_dir()` itself is created mode 0o700 so children are not accessible
anyway, and (c) the fix would add significant complexity.

---

#### INFO-04 — Debug log at `_start_authentication` exposes VPN request body
**File:** `openconnect_saml/authenticator.py:119`  
**Status:** ⚠ Flagged (cannot fix — authenticator.py is read-only for this agent)

```python
logger.debug("Sending auth init request", content=request)
```

The full XML request body is logged including the VPN URL and group.  Less
sensitive than SEC-01 but still unnecessarily verbose.

---

## Fixes applied

### `openconnect_saml/config_cmd.py` — schema validation before import write

Added pre-write validation in `_cmd_import` so invalid TOML cannot overwrite
the user's working config.

### `openconnect_saml/profiles.py` — sanitise username/group in NM export

Strip `\r\n` from `username` and `user_group` in `_profile_to_nmconnection`.

### `openconnect_saml/history.py` — handle OSError in export

Both CSV and JSON export paths now return 1 with an error message instead of
propagating an unhandled traceback on write failure.

### `openconnect_saml/fido2_auth.py` — correct base64 padding

`handle_fido2_challenge_headless` now uses `'=' * (-len(s) % 4)` for safe
padding of unpadded base64url strings.

---

## Coverage gaps closed

New test file: `tests/test_audit_api_coverage.py`

Key areas:
- `FIDO2Authenticator.authenticate()` — success path, ImportError path, no-device path,
  device-call failure (generic exception)
- `authenticator.py` — all async paths (HEADLESS_MODE, CHROME_MODE, Qt-mode),
  `CertRequestResponse` retry, `UnexpectedResponse` handling, `parse_auth_complete_response`
  error branches, `create_http_session` with ssl_legacy and no verify, XML builders
- `config_cmd.py` — `_cmd_edit` no-editor path, `_cmd_diff` error paths,
  `_cmd_import` invalid TOML, invalid schema, `_cmd_validate` clean and error paths
- `profiles.py` — nmconnection export (single / dir / multi-profile), XML import,
  profile migrate apply, profile copy / rename edge cases, import encrypted path
- `history.py` — export CSV/JSON success and error, `_parse_since` all branches,
  `compute_stats` empty/populated, `ConnectionTracker` full lifecycle
- `totp_providers.py` — `LocalTotpProvider` KeyringError path,
  `KeePassXCProvider.get_totp()` all error branches
