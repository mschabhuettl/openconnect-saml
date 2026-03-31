# Changelog

All notable changes to this project will be documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.5.0] - 2026-03-31

### Added
- **Multi-profile support** — save and switch between named VPN configurations
  - `openconnect-saml connect <profile>` to connect by profile name
  - `openconnect-saml profiles` to list, add, and remove profiles
  - TOML config: `[profiles.<name>]` sections with server, credentials, and settings
  - Fully backwards-compatible: no profile argument uses `default_profile` as before
- **Connection status TUI** — live VPN connection status display
  - `openconnect-saml status` shows profile, server, user, uptime, IP, TX/RX
  - `--watch` flag for live-updating display (refreshes every 2s)
  - Optional `rich` dependency: `pip install openconnect-saml[tui]`
  - Falls back to plain text output when `rich` is not installed
- **Shell completion** — tab completion for all shells
  - `openconnect-saml completion bash/zsh/fish` generates scripts
  - `openconnect-saml completion install` auto-installs to correct paths
  - Completes subcommands, flags, and profile names dynamically
- New CLI architecture with subcommands (`connect`, `profiles`, `status`, `completion`, `service`)
- 59 new tests (273 total)

## [0.4.0] - 2026-03-31

### Added
- **2FAuth TOTP integration** — fetch OTP codes from a [2FAuth](https://docs.2fauth.app/) instance via API
- Config: `totp_source = "2fauth"` in `[credentials]`, new `[2fauth]` section with `url`, `token`, `account_id`
- CLI: `--totp-source`, `--2fauth-url`, `--2fauth-token`, `--2fauth-account-id`
- Pluggable `TotpProvider` abstraction (`LocalTotpProvider`, `TwoFAuthProvider`)
- HTTPS enforcement warning for 2FAuth URLs
- Token never logged — only redacted references

## [0.3.0] - 2026-03-31

### Added
- **Chrome/Chromium browser** — Playwright-based alternative to Qt WebEngine (`--browser chrome`)
- **Systemd service** — `openconnect-saml service install/start/stop/status/logs`
- **Auto-reconnect** — automatic re-authentication on disconnect (`--reconnect`, `--max-retries`)
- **FIDO2/Yubikey support** — USB security key authentication for 2FA
- Backoff strategy: 30s → 60s → 120s → 300s between reconnect attempts
- New optional deps: `[chrome]` for Playwright, `[fido2]` for security keys
- 54 new tests (180 total)

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
