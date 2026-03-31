# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.2.0] - 2026-03-31

### Added
- **Headless/CLI mode** — browser-free SAML authentication via `--headless` flag
- Auto-authenticate: form parsing with username/password/TOTP injection
- Local callback server for MFA flows that require a browser
- PyQt6 now optional: `pip install openconnect-saml` works without GUI deps
- GUI extras: `pip install openconnect-saml[gui]` for browser mode
- 28 new headless tests (126 total)

### Fixed
- Browser tests properly skipped in CI (no display server)
- Platform-specific tests skipped on Windows
## [0.1.1] - 2026-03-30

### Improved
- Complete CI/CD pipeline: security scanning (pip-audit, bandit), Windows tests, coverage reports
- Automated release flow: tag → GitHub Release → PyPI → AUR
- Code formatting standardized with ruff

### Fixed
- CI compatibility with PyQt6 system dependencies
- Dev dependencies properly declared in pyproject.toml

## [0.1.0] - 2026-03-30

### About

First release of `openconnect-saml` — a maintained fork combining [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) with improvements from [kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).

### Added
- **SSL Legacy Renegotiation** — `--ssl-legacy` flag for servers requiring legacy SSL (upstream #81)
- **On-connect/disconnect scripts** — `--on-connect` and `--on-disconnect` hooks
- **CSD hostscan support** — `--csd-wrapper` passthrough to openconnect
- **No-sudo mode** — `--no-sudo` for unprivileged operation
- **Reset credentials** — `--reset-credentials` to clear stored keyring entries
- **Client certificate support** — handles client cert requests gracefully
- **Configurable HTTP timeouts** — `--timeout <seconds>` (default: 30)
- **Configurable browser window size** — `--window-size WIDTHxHEIGHT`
- **Microsoft Authenticator number matching** in default auto-fill rules
- **Office365 "Stay signed in?" auto-dismiss** in default rules
- **AUR PKGBUILD** for Arch Linux
- **PyPI publish workflow** (GitHub Actions on tag push)
- **98 tests** with comprehensive security test suite

### Improved
- **Python 3.10+** support (was 3.8+)
- **PyQt6** (was PyQt5)
- **hatchling** build system (was Poetry)
- **Modern asyncio** — removed deprecated `get_event_loop()` calls
- **importlib.resources** instead of deprecated `pkg_resources`
- **Robust TOTP handling** — graceful recovery from corrupt secrets (upstream #143, #193)
- **Better error messages** after 2FA failures with debug info (upstream #121)
- **Azure AD login compatibility** — dispatches change/input events on form fill (upstream #189)
- **Hostname in auth requests** for DeviceId (upstream #191)
- **auth.message handling** — defensive access with fallback (upstream #175, #161)

### Security
- **XXE protection** — safe XML parsers with `resolve_entities=False, no_network=True`
- **Command injection prevention** — `shell=False` + input validation for hooks
- **Config file permissions** — saved with `chmod 0600`
- **No credential logging** — passwords/secrets excluded from logs
- **Proper exceptions** — replaced `assert` with `AuthResponseError`

### Credits
- [László Vaskó (vlaci)](https://github.com/vlaci) — original openconnect-sso
- [Kowyo](https://github.com/kowyo) — openconnect-lite fork with modernization
- Community contributors whose PRs and issues shaped this release
