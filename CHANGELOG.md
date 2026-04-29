# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.2] – 2026-04-29

### Added

- **NetworkManager profile export (#22)** — `profiles export` now supports
  `--format nmconnection` to render a profile as a
  `.nmconnection` file compatible with the `network-manager-openconnect`
  plugin and the Ubuntu/GNOME VPN UI. UUIDs are derived from the profile
  name so re-exports overwrite the same connection in NM rather than
  duplicating it. Single profile → single file (or stdout); multiple
  profiles → write into a directory. Secrets are not written.
- **`--no-totp` / `--totp-source none` (#22)** — explicitly skip the
  interactive TOTP prompt for accounts that don't use TOTP. Saved into
  profiles by `setup` and `profiles add`, so subsequent `connect` runs
  no longer ask.
- **1Password & pass options in `setup` wizard** — the interactive setup
  wizard can now configure the 1Password and pass TOTP providers, not
  only `local`/`2fauth`/`bitwarden`/`none`.

### Fixed

- **Qt-mode hardware security keys (#24)** — Yubikey / Nitrokey / FIDO2
  keys now work with the Qt WebEngine browser. The `webAuthUxRequested`
  signal is wired to a UX handler that drives the SelectAccount /
  CollectPin / FinishTokenCollection / RequestFailed states. Requires
  Qt-WebEngine ≥ 6.7; older versions log a warning and recommend
  `--browser chrome`.
- **AUR publish workflow** — switched to `webfactory/ssh-agent`, which
  keeps the AUR signing key in memory instead of writing it to disk
  during the workflow run, and dropped debug output that exposed the
  key length and the first 50 characters of the key in CI logs.
- **`test_detect_device_no_fido2_library`** — robustly intercepts the
  import so the test passes regardless of whether the optional `fido2`
  extra is installed in the test environment.

### Changed

- `pyqt6` and `pyqt6-webengine` are now pinned to `>=6.7` (required for
  WebAuthn UX support). Existing installs continue to work, but FIDO2
  hardware-key flows in the Qt browser need the newer Qt.

## [0.8.1] – 2026-04-29

### Added

- Minimal `openconnect-saml gui` profile launcher for selecting saved profiles, connecting, disconnecting, and viewing process output.
- Chrome MFA diagnostics for push/number-challenge pages.

### Fixed

- `openconnect-saml connect <profile> --browser chrome` now honors the browser override instead of passing it through to OpenConnect.
- Chrome auto-fill recognizes more username fields and avoids repeated submit clicks that could refresh Duo/security-key pages.
- SAML auth-request parsing now handles namespaced `sso-v2-*` fields and newer Cisco/Duo form-action responses, with clearer diagnostics when login attributes are absent.

## [0.8.0] – 2026-04-17

### Added

- **1Password TOTP provider** — new `--totp-source 1password` that delegates
  OTP generation to the `op` CLI. New flags: `--1password-item`,
  `--1password-vault`, `--1password-account`. New `[1password]` config
  section with `item`, `vault`, `account` keys.
- **pass (password-store) TOTP provider** — new `--totp-source pass` using
  the `pass otp` extension. New flag `--pass-entry`; new `[pass]` config
  section with an `entry` key. Requires `pass-otp` to be installed.
- **Kill-switch** (Linux / iptables) — a new `killswitch` subcommand with
  `enable`, `disable`, and `status` actions. Installs a dedicated chain
  (`OPENCONNECT_SAML_KILLSWITCH`) that allows only loopback, the VPN server
  IP, configured DNS resolvers, and output on `tun*`/`utun*`/`ppp*`
  interfaces. Also reachable as a one-shot CLI flag: `--kill-switch`
  (alongside `--ks-allow-dns`, `--ks-allow-lan`, `--ks-no-ipv6`,
  `--ks-port`, `--ks-sudo`). Persistent configuration via
  `[kill_switch]` section.
- **Profile export / import / rename / show** — export a single profile or
  all profiles as JSON, with secrets stripped (`password`, `totp`,
  `totp_secret`, 2fauth `token`); import accepts single-profile or
  multi-profile payloads, supports `--as <name>` renaming and `--force`
  overwrite. New `profiles rename <old> <new>` and
  `profiles show <name> [--json]` commands.
- **`config` subcommand** — `config path` prints the config file path,
  `config show [--json]` prints the current configuration with secrets
  redacted, `config validate` performs schema and semantic checks (TOML
  syntax, profile `server` required, `active_profile` existence, missing
  `[2fauth]`/`[bitwarden]` sections for profiles that reference them,
  CIDR sanity on `routes`/`no_routes`, file-permission check), and
  `config edit` opens the file in `$EDITOR`.
- **`doctor` subcommand** — one-shot system diagnostics: Python version,
  `openconnect` binary presence, sudo/doas, `/dev/net/tun`, core and
  optional Python dependencies, keyring backend, config directory
  permissions, DNS resolution and TCP reachability of an optional
  `--server`, and whether the kill-switch is currently active.
- **Connection history** — every connect / disconnect / reconnect / error
  event is logged to `$XDG_STATE_HOME/openconnect-saml/history.jsonl`
  (owner-read 0o600, rotated at 512 KiB). New `history` subcommand with
  `show [--limit N] [--json]`, `clear`, and `path` actions. Opt-out per
  session with `--no-history` or globally via `connection_history = false`
  in the config.

### Changed

- `--totp-source` now accepts `local`, `2fauth`, `bitwarden`, `1password`,
  and `pass`.
- `ProfileConfig` and `Config` gained optional `onepassword`, `pass_` and
  `kill_switch` fields (all backwards-compatible, all default to `None`).
- Exit-code allocation for missing TOTP-provider configuration:
  `21` (2fauth), `22` (bitwarden), `23` (1password), `24` (pass).

### Fixed

- `profiles` management now properly updates `active_profile` when a
  profile is renamed.

### Notes

- All additions are opt-in and backwards-compatible. Existing configs,
  saved profiles, and CLI invocations continue to work unchanged.
- Kill-switch is Linux-only (iptables); on other platforms the command
  surfaces a clear `KillSwitchNotSupported` error.
- Connection history is enabled by default. It contains no secrets
  (only timestamps, server URL, profile name, username, and
  event/duration). Pass `--no-history` or set `connection_history =
  false` in config to disable.

## [0.7.1] – 2026-02-18

### Fixed

- Various small improvements.

## [0.6.0] – 2024

Initial public release of the maintained fork, combining features from
[vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) and
[kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).
