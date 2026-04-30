# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.17.0] – 2026-04-30

### Added

- **`profiles set NAME FIELD VALUE`** — programmatic, scriptable
  field editor for saved profiles. No editor invocation required:

  ```bash
  openconnect-saml profiles set work browser chrome
  openconnect-saml profiles set work notify true
  openconnect-saml profiles set work cert ~/certs/work.pem
  openconnect-saml profiles set work username alice@example.com
  openconnect-saml profiles set work browser ""        # clear override
  ```

  Allowed fields: `server`, `user_group`, `name`, `browser`, `notify`,
  `on_connect`, `on_disconnect`, `cert`, `cert_key`, `username`,
  `totp_source`. Booleans accept `true|false|yes|no|1|0|on|off`.
  Empty value clears optional fields.

### Notes

- Pure-additive UX release — no behaviour changes for existing
  workflows. Useful primarily in CI / automation scripts where
  `config edit` (which spawns `$EDITOR`) is impractical.

## [0.16.0] – 2026-04-30

### Added

- **`history show` filters** — three new flags for slicing the
  connection log:
  - `--filter PROFILE` keeps only events for the named profile
  - `--event {connected,disconnected,reconnecting,error}`
    keeps only the chosen event type
  - `--since WHEN` drops entries older than `WHEN` (ISO 8601
    timestamp, or relative phrase like ``"1 day ago"`` /
    ``"30 minutes ago"``)
  Filters compose; `--limit` applies after filtering. Works with
  the existing `--json` output.

### Notes

- Pure-additive UX release. Existing `history show` invocations
  behave unchanged when no filter flag is passed.

## [0.15.0] – 2026-04-30

### Added

- **`--version --check`** — opt-in PyPI lookup that surfaces a hint
  when a newer release is available. Best-effort with a 3-second
  timeout; never blocks normal startup. Plain `--version` still
  works exactly as before.
- **First-run hint** — running an interactive command on a system
  with no profiles configured prints a one-line "👋 Looks like
  this is your first run — try `openconnect-saml setup`" reminder.
  Skipped on non-TTYs and for `setup` / `completion` / `doctor` /
  `config` / `--version`.
- **`--auth-only`** — friendly alias for `--authenticate shell`,
  the most-used auth-only invocation. Useful for CI / scripts that
  just want to print the cookie and exit.

### Notes

- Pure UX release. No new runtime dependencies, no behaviour changes
  for users who don't opt in to the new flags.
- Network requests for `--version --check` go to
  `https://pypi.org/pypi/openconnect-saml/json` and respect a 3s
  timeout. Failure is silent — offline use is unaffected.

## [0.14.0] – 2026-04-30

### Added

- **Client-certificate authentication** — `--cert FILE` and
  `--cert-key FILE` flags. Profiles also gain `cert` and `cert_key`
  fields under `[profiles.<name>]` so each VPN can carry its own
  client cert. The paths are passed through to openconnect as
  `--certificate` / `--sslkey`. Tilde expansion happens at use time
  so `~/certs/work.pem` works as expected.
- **Encrypted profile backups** — `profiles export --format encrypted`
  produces a passphrase-protected file (Fernet AES-128-CBC + HMAC,
  PBKDF2-SHA256 with 480 000 iterations and a per-file random salt).
  The corresponding `profiles import FILE` autodetects the
  ``OPENCONNECT_SAML_BACKUP`` magic header and prompts for the
  passphrase. No new runtime dependency — `cryptography` ships with
  `keyring`/`secretstorage` on Linux.

### Notes

- Pure-additive release. Existing JSON exports / imports continue to
  work; encrypted backups are interchangeable with JSON ones — the
  payload format is identical, only the on-disk representation
  differs.

## [0.13.0] – 2026-04-30

### Added

- **`-q` / `--quiet` global flag** — raises the log threshold to
  `WARNING` for the duration of an invocation. Suppresses
  informational output without forcing the user to remember
  `--log-level WARNING`. Explicit `--log-level ERROR` still wins.
- **"Did you mean…?" suggestions** — when `connect <profile>` or
  `disconnect <profile>` cannot find the requested name,
  Python's `difflib.get_close_matches` surfaces the three most
  similar candidates so typos are immediately fixable.
- **Setup wizard XML auto-discovery** — at startup, `setup` scans
  `/opt/cisco/anyconnect/profile`,
  `/opt/cisco/secureclient/anyconnect/profile`, and `~/.cisco/profile`
  for `.xml` profiles. If any are found, it offers to bulk-import
  them — same logic as `profiles import-xml` but pre-applied so new
  users don't have to know about that subcommand.
- **Shell-completion coverage** — the `bash` script now completes
  `disconnect`, `sessions`, `groups`, `history`, `killswitch`, and
  `config` subcommands and their actions / arguments. New hidden
  helpers `completion _groups` / `_sessions` feed dynamic name
  lists into bash / zsh / fish.

### Notes

- Pure-additive UX release. No new runtime dependencies, no
  behaviour changes for users not opting in to the new flags.

## [0.12.0] – 2026-04-30

### Added

- **`profiles import-xml FILE`** — bulk-import VPN profiles from an
  AnyConnect ``.xml`` profile file (the same format
  ``openconnect`` already reads from
  ``/opt/cisco/anyconnect/profile/*.xml``). Each ``HostEntry`` becomes
  one saved profile keyed by ``HostName``. ``--prefix STR`` namespaces
  the imports; ``--force`` overwrites existing profiles with the same
  name.

- **Profile groups** — `[profile_groups.<name>]` lists profile keys
  to connect / disconnect together:

  ```toml
  [profile_groups]
  work = ["vpn-eu", "vpn-us"]
  ```

  Or via CLI: `openconnect-saml groups add work vpn-eu vpn-us`. Then
  `openconnect-saml groups connect work` brings every member up in
  detached mode and `groups disconnect work` stops them all. Other
  actions: `groups list`, `groups remove`.

### Notes

- Pure-additive release; existing CLI flags, configs, and profiles
  continue to work unchanged.
- ``Config.profile_groups`` is a new top-level dict (default empty).
  Older tools loading the config see an empty dict if the field is
  absent, no migration required.

## [0.11.0] – 2026-04-30

### Added

- **Per-profile setting overrides** — `[profiles.<name>]` now accepts
  five optional fields that take precedence over the corresponding
  top-level config / CLI defaults:
  - `browser` — `qt` / `chrome` / `headless`
  - `notify` — `true` / `false`
  - `on_connect` / `on_disconnect` — shell command strings
  - `kill_switch` — full `[kill_switch]`-shaped subsection (per-profile
    enabled / allow_lan / ipv6 / dns_servers)

  When unset (default), behaviour is unchanged — top-level config or
  CLI flag wins. Resolution order is always **CLI > per-profile >
  top-level config**.

- **`profiles add --browser BACKEND` and `--notify`** — set those
  fields directly when creating a profile.

- **Config schema versioning** — new `schema_version = 1` field on the
  top-level `Config`. Future breaking changes bump this and surface a
  hint in `profiles migrate`. Existing configs without the field
  default to schema 1 transparently.

### Notes

- Pure-additive release; existing CLI flags, config files, and
  profiles continue to work unchanged.
- All overrides are stripped from `as_dict()` when ``None``, so saved
  configs don't grow noisy `<field> = ""` rows.

## [0.10.0] – 2026-04-30

### Added

- **Multi-session support** — connect to several VPN gateways
  simultaneously without juggling shells:
  - `connect --detach` daemonises the openconnect process after auth so
    `openconnect-saml` exits while the tunnel keeps running.
  - `disconnect [PROFILE]` stops a specific session by profile name;
    `disconnect --all` stops every active session at once.
  - `sessions list [--json]` enumerates every recorded live session
    (profile, pid, server, started_at). Stale records are pruned on
    read.
- **Session state file** — `$XDG_STATE_HOME/openconnect-saml/sessions/<profile>.json`
  (mode `0600`). Owned by the user, holds metadata only (profile name,
  server, username, pid, parent pid, start timestamp). Never any
  secrets.
- **Status / TUI / GUI now consume session records** — when one or
  more recorded sessions are live, `status` prefers the recorded
  metadata over `pgrep` output; falls back to pgrep when no record
  matches.

### Notes

- `connect --detach` requires sudo to be cached (or `NOPASSWD`) since
  the openconnect-saml supervisor process exits before openconnect
  finishes prompting. For interactive use, run plain `connect` and
  push it to the background with `Ctrl-Z` + `bg` if needed, or stick
  to `--reconnect` for long-running supervisor mode.
- All additions are opt-in / backwards-compatible. Existing CLI flags,
  config files, profiles, and history continue to work unchanged.

## [0.9.0] – 2026-04-29

### Added

- **Interactive TUI** — new `openconnect-saml tui` subcommand opens a
  full-screen, keyboard-driven terminal UI with:
  profile list (↑/↓ to select, Enter / `c` to connect), live status
  pane with traffic counters and rate, history view (`h`), refresh
  (`r`), disconnect (`d`), quit (`q`). Requires the `[tui]` extra
  (`rich`).
- **Expanded GUI** — `openconnect-saml gui` got a tabbed Tk interface:
  *Profiles* tab (list with full schema, Add / Edit / Delete dialogs,
  Connect / Disconnect, log pane), *Status* tab (live counters / rate
  refreshed every 2s), *History* tab (recent events refreshed every
  5s), and a global Browser-backend selector in the toolbar.
- **macOS kill-switch via `pf`** *(experimental)* — second backend for
  the existing `killswitch enable / disable / status` commands. Loads
  a self-contained pf anchor (`openconnect-saml-killswitch`) without
  touching `/etc/pf.conf`. Linux iptables behaviour is unchanged.
- **`profiles migrate` subcommand** — schema clean-ups for existing
  configs:
  - lift legacy `[default_profile]` into `[profiles.default]` so
    everything is multi-profile-aware
  - drop unused `[2fauth]` / `[bitwarden]` / `[1password]` / `[pass]`
    sections that no profile references anymore
  Dry-run by default; `--apply` persists changes.
- **`doctor --json`** — machine-readable diagnostics output for
  monitoring / scripting. Mirrors the exit-code logic of the
  human-readable variant (0 OK / 1 fail / 2 warn).
- **`status --watch` bandwidth rate** — TX / RX deltas computed
  between samples; surfaced as a new `Rate ↑/↓` row in plain / rich /
  JSON output.

### Changed

- **`app.py` TOTP-provider configuration extracted** into two
  testable helpers: `resolve_totp_source(args, credentials)` (pure)
  and `configure_totp_provider(args, cfg, credentials)` (mutating).
  The `_run` async function shrank by ~80 LoC and gained a new test
  module (`tests/test_totp_resolver.py`) covering every provider's
  CLI / config-fallback / missing-config path.

### Notes

- macOS pf backend is marked **experimental**; iptables remains the
  reference implementation. macOS users should still expect to test
  with `--browser chrome` for hardware-token flows since Qt-WebEngine
  on macOS sometimes builds without WebAuthn.
- All additions are opt-in / backwards-compatible. Existing
  CLI flags, config files, and saved profiles continue to work
  unchanged.

## [0.8.5] – 2026-04-29

### Changed

- **Documentation overhaul** — the previous 750-line README.md is now
  a 100-line landing page that links into a topic-per-file `docs/`
  reference. Eleven new files cover installation, browser backends,
  authentication / TOTP / FIDO2, profiles, networking (split-tunnel +
  kill-switch), operations (reconnect / systemd / status / history /
  notifications / hooks), configuration, diagnostics, the full CLI
  reference, contributor setup, and migration guides. No content was
  dropped; existing flows are easier to find. See [docs/README.md](docs/README.md)
  for the index.

### Notes

- Pure documentation release. No code, behaviour, or CLI surface
  changes; existing scripts, configs, and profiles continue to work
  unchanged.

## [0.8.4] – 2026-04-29

### Added

- **`--config FILE` global flag** — overrides the default XDG config
  path for the duration of one invocation. Also reads
  `OPENCONNECT_SAML_CONFIG` from the environment for non-interactive
  use (CI, multi-tenant setups, automated tests). Works with every
  subcommand and the legacy CLI form.
- **`status --json`** — machine-readable output for monitoring
  scripts / Prometheus exporters / dashboards. Emits a single JSON
  object per invocation with `connected`, `server`, `interface`, `ip`,
  `uptime`, `tx`, `rx`, `profile`, `user`, `reconnects`. Compatible
  with `--watch`.
- **`history stats` subcommand** — aggregates connect/disconnect
  events into a summary: total connections, total time online, mean
  session length, error count, profile usage breakdown, last-connect
  timestamp. Accepts `--json`. Uses the existing `history.jsonl`
  audit log; no extra storage.
- **`doctor` SAML endpoint probe** — when `--server <host>` is
  provided, runs an HTTPS probe of the URL and verifies the response
  looks like an AnyConnect SAML page (200/302/303/307 or
  `Server: ... AnyConnect ...`). Catches misconfigured URLs (404 to
  the wrong path), TLS errors, and corporate proxies that intercept
  the gateway.

### Notes

- All additions are opt-in and backwards-compatible. Existing
  workflows continue to work without changes.
- The HTTP probe in `doctor` uses `requests` (already a core
  dependency); it follows redirects only when the server explicitly
  returns 3xx with a `Location` header.

## [0.8.3] – 2026-04-29

### Changed

- **Refactored `config.py`** — five near-identical `_convert_<provider>`
  helpers replaced with a single `_node_converter(cls)` factory; the
  TOML-key/Python-attr renaming (`2fauth` ↔ `twofauth`,
  `1password` ↔ `onepassword`, `pass` ↔ `pass_`) is now table-driven
  via `_TOML_KEY_ALIASES`, removing duplicated `from_dict` / `as_dict`
  bodies on `ProfileConfig` and `Config`. Behaviour is identical;
  the TOML serialization round-trips byte-for-byte.
- **Centralized XXE-safe XML parser** — `_make_safe_parser()` in
  `authenticator.py` and `profile.py` consolidated into
  `openconnect_saml.xml_utils.make_safe_parser()`. Same
  `resolve_entities=False`, `no_network=True` defaults.
- **GUI now respects the chosen browser backend** — the `gui` launcher
  no longer hardcodes `--browser chrome`; it offers a Browser dropdown
  (chrome / qt / headless) so users on platforms where Playwright is
  broken (e.g. Ubuntu 26.04, #22) can pick Qt or headless instead.
- **`logger.warn()` → `logger.warning()`** — replaced 16 deprecated
  calls across `app.py` and `browser/browser.py` so Python 3.14+
  doesn't emit `DeprecationWarning` at runtime.

### Fixed

- **AUR `.SRCINFO` generation** — the workflow used to write
  `sha256sums = SKIP` while `PKGBUILD` carried the real checksum, and
  emitted a non-existent `download = …` field. Now both files share the
  same `sha256` and `.SRCINFO` is produced in a single atomic commit
  alongside `PKGBUILD` (no more two-commit churn per release).
- **Windows test failure** — `test_export_nmconnection_to_file` asserted
  POSIX `0o600` mode bits; split into a portable test plus a
  POSIX-only test gated on `platform.system() != "Windows"`.

### Notes

- No CLI / config / profile-format changes; pure-internal release.
  Existing installs upgrade transparently.

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

## [0.6.0] – 2024-01-01

Initial public release of the maintained fork, combining features from
[vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) and
[kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).
