# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.24.2] – 2026-05-06

Documentation + AUR packaging follow-ups on top of v0.24.1. No code
changes to the runtime — same wheel as v0.24.1 plus updated docs and
a regenerated AUR `PKGBUILD` / `.SRCINFO`.

### Docs

- `docs/authentication.md` is more honest about distro-vs-PyPI Qt
  builds for FIDO2 hardware keys: PyPI's `PyQt6-WebEngine` is
  confirmed broken (WebUSB stripped at compile time, #24), but
  distro `qt6-webengine` packages (Arch, Debian, Fedora, …) build
  from upstream Qt sources and may have WebUSB enabled. Marked as
  **unverified, please test and report on #24** — replaces the
  earlier blanket "use --browser chrome" recommendation with one
  that depends on how the user installed.
- New caveat in the `--chrome-channel` section: Playwright doesn't
  expose a `chromium` channel, so plain `pacman -S chromium` users
  can't skip the Playwright download via the new flag. Two
  workarounds documented (AUR `google-chrome`, or just run
  `playwright install chromium` once).

### Packaging

- AUR `PKGBUILD` is now regenerated from scratch by
  `aur-publish.yml` on every release, instead of being
  sed-patched. That eliminates the drift risk between `PKGBUILD`
  and `.SRCINFO` (deps used to live in two places).
- New `optdepends` in the AUR package:
  - `python-rich` — rich-formatted output for the `status` and
    interactive `tui` subcommands (without it, both fall back to
    plain text).
  - `python-playwright` — required for `--browser chrome` backend
    (run `playwright install chromium` after install).
  - `python-fido2` — hardware-key (Yubikey / Nitrokey) auth in
    `--browser headless` mode.
  - `keepassxc`, `bitwarden-cli`, `1password-cli`, `pass`,
    `pass-otp` — TOTP-source backends, only needed if the user
    actually uses the matching `--totp-source`.

## [0.24.1] – 2026-05-06

### Added

- **`--chrome-channel CHANNEL` flag.** When using `--browser chrome`,
  pick a system-installed Chrome / Edge instead of letting Playwright
  download its bundled Chromium (~150 MB). Valid values: `chrome`,
  `chrome-beta`, `chrome-dev`, `chrome-canary`, `msedge`, `msedge-beta`,
  `msedge-dev`, `msedge-canary`. Default unchanged (Playwright bundled
  Chromium). Closes the request from #24 to reuse already-installed
  browsers.

### Docs

- `docs/authentication.md` calls out that **`--browser qt` cannot
  drive FIDO2 hardware-key MFA on PyPI installations**. The PyPI
  `PyQt6-WebEngine` wheel ships Chromium with WebUSB compiled out
  entirely, so `navigator.credentials.get()` for USB security keys
  is silently rejected before WebAuthn ever fires (root cause for
  #24's "Yubikey LED never blinks" symptom). Recommends `--browser
  chrome` (with optional `--chrome-channel` for system Chrome) or
  `--auth-script` as the supported FIDO2 paths.

### CI

- Pipeline action bumps validated end-to-end via the new
  `workflow_dispatch`-triggerable `release.yml` / `publish.yml`:
  `astral-sh/setup-uv@v7` (was v4), `actions/download-artifact@v8`
  (was v4). Closes Dependabot #34 + #32 in favour of #36.

## [0.24.0] – 2026-05-06

A maintenance + features release: two new authentication
backends (KeePassXC TOTP, experimental ADFS / WS-Trust scripted
flow), an mkdocs-material site, contributor docs (CONTRIBUTING,
CODE_OF_CONDUCT), a CHANGELOG backfill of older releases, a
coverage push from 60% to 76%, plus pre-commit and Dependabot
plumbing. No breaking changes.

### Added

- **Federated Microsoft Entra (ADFS / WS-Trust 2005) scripted flow.**
  Closes the federated half of the Entra path that was bailing out
  with a clean error since v0.22.4. When `GetCredentialType` reports
  `FederationRedirectUrl`, the wrapper now:
  1. Hits Microsoft realm-discovery (`getuserrealm.srf`) to find the
     tenant's WS-Trust 2005 endpoint;
  2. POSTs a SOAP envelope (UsernameToken with the user's password)
     to that endpoint;
  3. Extracts the SAML 1.1 assertion from the RSTR;
  4. Wraps it in a `wresult` POST to `login.microsoftonline.com/login.srf`
     so MS issues federated-auth cookies;
  5. Picks up the regular post-password page, which carries the
     SAMLResponse form bound for the SP / Cisco gateway.

  Marked **experimental** — the flow is well-spec'd but we don't have
  a federated test tenant in CI, so the first real-world failure
  will surface in a user issue. Logs a clear startup warning and
  recommends `--browser chrome` as the fallback. All POST targets
  (realm-discovery, WS-Trust endpoint, login.srf) are checked
  against `--allowed-hosts`. Password is XML-escaped in the SOAP
  body.

- **KeePassXC TOTP provider** (`--totp-source keepassxc`). Reads
  the OTP from a `.kdbx` database via `keepassxc-cli show -a TOTP`.
  New flags: `--keepassxc-db PATH`, `--keepassxc-entry NAME`,
  `--keepassxc-keyfile PATH` (optional). Database password comes
  from `KEEPASSXC_DB_PASSWORD` env var (preferred for unattended
  runs) or an interactive `getpass` prompt; never on argv.
  Profile-persistable as `[keepassxc]` config section.

### Docs / Project hygiene

- New `CONTRIBUTING.md` (dev setup, issue/PR conventions, release
  policy = main + tags / no per-version branches, project
  layout walkthrough).
- New `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1, by reference).
- README "Credits" expanded to thank named contributors from recent
  issues and PRs.
- mkdocs-material site at `mkdocs.yml` + `.github/workflows/docs.yml`
  rebuilds + deploys to GitHub Pages on every push to main that
  touches `docs/`.
- Backfilled CHANGELOG entries for v0.1.0 through v0.7.1 from the
  per-tag git log so every released version has notes.

### CI / Testing

- Coverage exclusions for `gui.py`, `interactive_tui.py`,
  `browser/browser.py`, `browser/chrome.py` (Qt / Playwright code
  that can't honestly run in CI). Baseline rises from 60.65% to
  76.25% on Linux across five focused rounds; floor raised from
  50 to 73 (the cross-platform minimum — Windows lands ~3 points
  lower because `killswitch.py`'s iptables/pf code and a few
  `pgrep`/`/proc` paths can't run there).
- `test_headless_entra.py` (18 cases) covering the scripted
  Microsoft Entra flow: guardrails, federated / passwordless
  forks, happy path, wrong-password, unscriptable MFA branch,
  WS-Trust SOAP envelope shape, end-to-end mocked WS-Trust flow.
- `test_keepassxc.py` (12 cases) for the new TOTP provider.
- `test_app_helpers.py` + `test_killswitch_helpers.py` (44 cases)
  for `_validate_hook_command`, hook handlers, logger config,
  killswitch platform / backend / IP-resolution helpers.
- `test_cli_handlers.py` (24 cases) for the small subcommand
  handlers (`disconnect`, `sessions`, `run`, plus the missing
  groups branches).
- `test_setup_wizard.py` extended (+16 cases): EOF / ^C interrupt
  branches, AnyConnect XML scan/import, 1Password + pass +
  advanced-mode wizard branches.
- `test_tui.py` extended (+39 cases) covering format helpers,
  `_augment_with_rate`, `_find_vpn_process`, `_print_status_json`,
  `_plain_output`, `_check_killswitch_active`, interface helpers
  (`_get_vpn_interface`, `_get_interface_ip`),
  `_collect_all_statuses`, the rich renderer, and the watch loop.
- `.pre-commit-config.yaml` with ruff + EOL/whitespace hygiene
  (opt-in via `pre-commit install`).
- Dependabot watching pip + GitHub Actions weekly; pytest+ruff
  patches grouped, majors individual.

## [0.23.0] – 2026-05-05

### Added

- **External authentication script (`--auth-script PATH`, also a
  per-profile `auth_script` field).** When set, the wrapper hands
  the SAML phase off to your script: the script gets
  `<login_url> <token_cookie_name> <username>` on argv with the
  password on stdin, must print the SSO token to stdout, and gets
  `--timeout` seconds to do so. Useful for IdPs the built-in
  scripted flow can't drive (in-house SSO, ADFS / WS-Trust, bespoke
  MFA). The subprocess only inherits `PATH` and `HOME` — anything
  else has to be set explicitly inside the script. When `auth_script`
  is read from a profile config (vs CLI) the wrapper logs a
  `WARNING` so a malicious config edit can't silently inject
  code-execution under sudo. Thanks @derkarnold for #29.

## [0.22.5] – 2026-05-05

### Diagnostic

- **`--browser qt --log-level DEBUG` now traces the WebAuthn surface**
  (#24 follow-up). The v0.21.0 fix unblocked the slot-signature crash
  on Qt 6.11+, but the follow-up report shows `webAuthUxRequested`
  still never fires for some users when DUO asks for a security key
  — Yubikey/Nitrokey LEDs don't blink. Existing logging was silent
  on why. v0.22.5 wires four new diagnostic streams behind
  `--log-level DEBUG`:

  - Every JavaScript ``console.log/warn/error`` from the IdP page,
    so DUO's WebAuthn capability detection (`credentials.create`
    availability, feature-flag checks, …) is visible.
  - ``featurePermissionRequested`` for Geolocation / Mic / Camera /
    Notifications.
  - ``selectClientCertificate`` (some IdPs route key auth via it).
  - Every ``urlChanged``, including hash-fragment redirects that
    ``loadFinished`` alone misses.

  Plus a startup `libfido2` availability probe — on Linux,
  QtWebEngine delegates the actual hardware-key ceremony to libfido2,
  and missing libfido2 / udev rules is a common silent reason
  WebAuthn never reaches the key. If the lib isn't found we log a
  clear warning naming the distro package + ``/dev/hidraw*``
  permission requirement.

  No behaviour change for non-debug runs.

## [0.22.4] – 2026-05-04

### Added

- **Console-only Microsoft Entra ID / Azure AD login** — closes the
  follow-up half of #19. The original cert-verification half was
  already fixed in v0.22.0 + v0.22.2; the reporter then asked
  whether *fully* console-based VPN bring-up was planned for MS365
  SSO. It is now: when the IdP is Entra
  (`login.microsoftonline.com` and friends) the headless
  authenticator drives Microsoft's multi-step login protocol
  directly via HTTPS POSTs: `GetCredentialType` → password →
  MFA / TOTP → KMSI ("Stay signed in?") → SAMLResponse. No browser
  binary, no DISPLAY, no callback server. Works for tenants that
  accept username + password + TOTP. Tenants that mandate FIDO2 /
  phone-push / conditional-access surface a clear
  `HeadlessAuthError` pointing at `--browser chrome` instead (which
  also runs Chromium headless via Playwright — no DISPLAY needed),
  since those flows can't be scripted from a pure-HTTP path. Every
  Entra POST target is checked against `--allowed-hosts` before
  credentials or the SAMLResponse leave the process.
- **Friendlier `--browser chrome` startup error** when the Chromium
  binary is missing (extras installed but `playwright install
  chromium` was skipped).

### CI

- **Integration tests skip on Windows.** They drive long-lived
  subprocess + mock-HTTPS-server interactions that flaked
  intermittently on the Windows GHA runner (slower TIME_WAIT, mock
  gateway thread shutdown timing). Two consecutive identical CI runs
  on the v0.22.3 commit produced one green and one red Windows job —
  the latter held the PyPI publish back. Linux + macOS still cover
  the integration suite, plus all unit tests run on Windows.

### Notes

- v0.22.3 made it to GitHub Releases + AUR but **not** to PyPI: the
  `publish.yml` gate flaked on Windows even though the identical
  `release.yml` gate on the same commit was green. Skipping
  integration tests on Windows in this release removes that flake
  vector going forward.


## [0.22.3] – 2026-05-01

### Fixed (Windows)

- **`UnicodeEncodeError` on `cp1252` console** — Windows defaults
  stdout/stderr to the active console codepage (typically cp1252),
  which can't encode the `→` / `✓` / `✗` glyphs we use in CLI output
  (`profiles add`, `config validate`, etc.). A bare `print(...)`
  containing one of those crashed the whole command on a Windows
  console. The CLI entry point now reconfigures stdout/stderr to
  UTF-8 with `errors="replace"` on Windows.
- **`getpass.getpass` blocked on Windows when stdin was piped** —
  on Windows `getpass.getpass` reads from the console handle
  (``msvcrt.getwch``), not from `sys.stdin`. Subprocess-driven runs
  (CI, scripts, ``run`` mode) that supply a password via stdin
  blocked forever waiting for console input. New `_read_password()`
  helper in app.py uses `sys.stdin.readline` when stdin isn't a
  TTY and `getpass` otherwise.
- **`_pid_alive` raised `OSError [WinError 87]` for stale PIDs** —
  on Windows `os.kill(missing_pid, 0)` raises a generic `OSError`
  instead of `ProcessLookupError`. We now catch the bare `OSError`
  and treat it as "not alive" so stale session records get pruned
  cleanly instead of propagating the error up.
- **`sessions.kill()` crashed on Windows when the SIGTERM grace period
  expired** — the escalation step did `os.kill(pid, signal.SIGKILL)`,
  but `signal.SIGKILL` doesn't exist on Windows (`AttributeError`).
  The function now uses `getattr(signal, "SIGKILL", None)` and skips
  the escalation on platforms without it. Windows' `SIGTERM` is
  already an unconditional `TerminateProcess`, so skipping the
  escalation matches existing runtime behaviour.
  `tests/test_coverage_additions.py` carries
  `@pytest.mark.skipif(not hasattr(signal, "SIGKILL"))` for the
  matching test.
- **`profiles add` wizard prompted in subprocess-driven test runs** —
  `is_interactive = sys.stdin.isatty()` returned `True` on Windows
  even for an inherited `subprocess.DEVNULL` / nul stdin, so the
  wizard fired and EOF'd. Tightened to
  `sys.stdin.isatty() and sys.stdout.isatty()`: scripted callers
  always capture stdout (so isatty=False) and real users at a
  terminal don't.
- **`cryptography` is now an explicit `[dev]` extra** — the encrypted
  backup tests and the integration mock gateway both lazy-import
  `cryptography`. On most Linux setups it arrives transitively via
  other deps, but on Windows the dep tree didn't pull it in, so
  ~12 tests failed with `ModuleNotFoundError`. Now declared.

### CI

- **Windows job (`test (windows-latest, 3.12)`) now also routes
  pytest output through `tee pytest-output.txt` with
  `set -o pipefail`** and sets `PYTHONIOENCODING=utf-8`. Without
  that the cp1252 default codepage tripped pytest/coverage during
  the terminal report on Windows runners. Linux/macOS jobs are
  unaffected.

### Notes

- v0.22.2 was tagged but never reached PyPI / AUR — the release gate
  added in v0.22.2 caught the Windows matrix failure and held back
  every downstream job (`build`, `publish`, `Create GitHub Release`,
  `Trigger AUR update` all `skipped`). v0.22.3 is what actually
  ships the v0.22.2 changes (issue #19 follow-up + the Copilot
  coverage tests from PR #25) plus the four Windows-specific fixes
  above.

## [0.22.2] – 2026-05-01

### Fixed

- **Wrapper-only flags placed after `--` were silently forwarded to
  openconnect (#19)** — `openconnect-saml connect work --reconnect --
  --no-cert-check` looked like it should disable cert verification
  for the wrapper, but the `--` made argparse stop and the flag ended
  up appended to openconnect's argv (where it doesn't exist). The
  wrapper-side TLS verify still fired and the user saw
  `CERTIFICATE_VERIFY_FAILED`. We now hoist `--no-cert-check`,
  `--ssl-legacy`, `--reconnect`, `--background`, `--allowed-hosts`,
  `--on-error`, and `--wait` back onto the wrapper when they appear
  in the openconnect-args list, with a stderr warning explaining
  the corrected placement. Genuinely-openconnect flags
  (`--no-dtls`, `--script`, ...) are unchanged.
- **`requests.exceptions.SSLError` in the SAML phase now logs a
  helpful hint** pointing at `--no-cert-check` instead of letting
  the bare TLS traceback bubble up. The cert hash is still pinned
  via openconnect's `--servercert`, so the bypass only affects the
  requests-side handshake.

### Tests

- **+38 unit tests across 8 modules** (Copilot coverage analysis,
  PR #25): `version`, `saml_authenticator`, `completion`,
  `encrypted_backup`, `sessions`, `version_check`, `profile`, and
  `notify` are now at 100% line coverage. Overall coverage 59.5%
  → 61.1%; suite is at 750 tests (was 709).

## [0.22.1] – 2026-04-30

### Fixed

- **`connect PROFILE --reconnect` (and other known flags) was forwarded
  to `openconnect`** — the `openconnect_args` positional used
  `argparse.REMAINDER`, which is greedy and swallows known flags placed
  *after* the profile name. `--reconnect` was prefix-matched as
  `openconnect --reconnect-timeout`, ate the server URL as its value,
  and openconnect bailed out with `No server specified`. Replaced with
  `parse_known_args`, so known flags are parsed and only truly-unknown
  args (everything after `--`, or anything argparse can't claim) are
  forwarded. Surfaced by a real-world test against `univpn.uni-graz.at`.
- **Empty TOTP input caused a forever re-prompt loop** — hitting Enter
  at the `TOTP secret (leave blank if not required)` prompt stored the
  empty string in keyring. `pyotp` then logged
  `Non-base32 digit found` on every reconnect, and the prompt came
  back. Now an empty answer sets `totp_source = "none"` and clears the
  stale entry from keyring, so the opt-out is remembered. The keyring
  side also auto-purges any pre-existing corrupt secret on first read
  (#143 follow-up).
- **`openconnect-saml tui` on Arch suggested the wrong install
  command** — the error said `pip install openconnect-saml[tui]`, but
  Arch users install `python-rich` from pacman. The hint is now
  distro-aware (Arch / Debian-Ubuntu / Fedora-RHEL) via `/etc/os-release`
  and falls back to the pip command otherwise.

## [0.22.0] – 2026-04-30

### Fixed

- **`--no-cert-check` had no effect on most Linux distros (#19 redux)** —
  setting `session.verify = False` is silently overridden by the
  `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` env vars (which most distros
  set by default). Now we also flip `session.trust_env = False` when
  the user opts out of cert verification, so the flag actually works.
  Affects both the SAML auth session and the headless authenticator.
- **`profiles add` aborted in non-interactive runs** — the wizard
  prompted for `username` / `user_group` whenever they weren't on the
  command line, even with no controlling TTY. The prompt would receive
  EOF and exit. Now we only prompt when stdin is a TTY, and require
  `--server` explicitly otherwise. Restores CI / scripting use.
- **`openconnect-saml --quiet status` (and other global-flag-then-
  subcommand combinations) misclassified as legacy mode** — argparse
  ran the legacy connect dispatcher and bailed on missing `--server`.
  The legacy detector now skips past `--config FILE`, `--quiet`,
  `--check` before deciding.

### Added

- **End-to-end integration test harness** (`tests/integration/`) — an
  in-process mock Cisco AnyConnect gateway + SAML IdP on a single
  HTTPS origin (self-signed cert generated at runtime) lets the test
  suite drive the real CLI through the full auth flow. 38 new
  integration tests (706 total) covering auth → cookie roundtrip,
  profile lifecycle, sessions / disconnect / groups / history /
  doctor / migrate, and `--no-cert-check` against a real self-signed
  cert. The three bugs above were all surfaced by this harness.
- **Documentation completion pass** — every CLI surface added in
  v0.8.2–v0.21.0 is now documented under `docs/` (cli-reference,
  operations, networking, profiles, configuration, authentication,
  diagnostics). Previously-undocumented: `profiles copy`,
  `profiles set`, `--no-cert-check`, `--allowed-hosts`, `--on-error`,
  `--auth-only`, `--background`, `--wait`, `config import`,
  `config diff`, `groups rename`, `setup --advanced`,
  `--version --check`, `service install --user`, `run`,
  `history export`, `--cert` / `--cert-key`, `schema_version`.

### Notes

- This release is bug-fix-only on the runtime side; behaviour for
  previously-working invocations is unchanged. The fixes restore
  flags that were broken for at least one common scenario each.

## [0.21.0] – 2026-04-30

### Fixed

- **Qt browser regression in v0.8.2 (#24)** — the WebAuthn UX handler
  was decorated with ``@pyqtSlot(object)``, which PyQt6 6.11+ rejects
  with `TypeError: decorated slot has no signature compatible with
  webAuthUxRequested(QWebEngineWebAuthUxRequest*)`. This broke
  `--browser qt` mode entirely on modern PyQt builds, regardless of
  whether WebAuthn was involved. The decorator is now removed so
  PyQt accepts the slot without strict signature matching, and the
  `userNames` property is read both as a callable and as an attribute
  for cross-version compatibility.
- Diagnosis credit: [@salty-flower](https://github.com/salty-flower) on #24.

### Added

- **`--on-error CMD` hook** — runs a command if authentication or
  connect fails. The exit code is exposed to the hook via the `RC`
  environment variable (e.g.
  `--on-error 'curl -X POST -d "vpn failed: $RC" ...'`). Useful for
  alerting / monitoring integrations.
- **`groups rename OLD NEW`** — round out the group-management API.
  Symmetric with `profiles rename`.

### Notes

- This release is pure-additive *plus* the regression fix. Users on
  v0.8.2–v0.20.0 with `--browser qt` and PyQt6 ≥ 6.11 should
  upgrade — the previous releases would raise the slot-signature
  error before the browser even loaded.

## [0.20.0] – 2026-04-30

### Added

- **`profiles copy SRC DST`** — duplicate a saved profile under a new
  name. ``--force`` overwrites an existing target.
- **`config import FILE`** — merge another TOML config into the
  active one. By default existing keys win (keeps your overrides
  safe); ``--force`` lets the incoming file replace them. Dicts are
  merged recursively, lists/scalars wholesale.
- **`service install --user`** (and the rest of the `service` actions)
  — install per-user systemd units under
  ``~/.config/systemd/user/`` and manage them with `systemctl --user`.
  No `sudo` required. Existing system-unit deployments are
  auto-detected so you don't have to remember which mode you used.
- **`--no-cert-check`** — disables TLS verification for the SAML
  auth phase (and passes `--no-system-trust` through to openconnect).
  Closes the gap that left issue #19 reachable.
- **`--allowed-hosts HOST,HOST,...`** for headless mode — explicit
  hostname whitelist for the redirect chain (supports `*.suffix`
  globs). The gateway and login URL hosts are auto-allowed; any
  redirect off that path is refused with a clear `HeadlessAuthError`.
  Closes the long-open #11 security gap.
- **`schema_version` bumped to 2** — first real migration in the
  framework. ``profiles migrate`` adds `schema_version = 2` to
  configs that don't have it; existing v1 configs continue to load
  unchanged.

### Notes

- All additions are pure-additive. Existing CLI flags, configs, and
  workflows continue to work without changes. No new runtime
  dependencies.

## [0.19.0] – 2026-04-30

### Added

- **`run PROFILE -- COMMAND ARGS`** — transient session subcommand:
  brings the profile up in detached mode, waits for the tunnel,
  runs `COMMAND` with `ARGS` in the foreground, and tears the
  tunnel down on exit. Useful for one-shot tasks that need the VPN:
  ```bash
  openconnect-saml run work -- curl https://internal.example.com
  openconnect-saml run --wait 30 work -- ssh prod.internal
  ```
- **`history export`** — write the JSONL audit log to CSV or JSON
  (`--format csv|json`, `-o FILE` for output, stdout otherwise).
  CSV columns: timestamp, event, profile, user, server,
  duration_seconds, message — directly importable into spreadsheets
  or BI tools.
- **`config validate` checks external TOTP binaries** — when a
  profile uses `totp_source = 1password / bitwarden / pass`, the
  validator now warns if the corresponding `op` / `bw` / `pass`
  binary isn't on PATH, so misconfigurations surface before the
  first connect attempt rather than during one.
- **Kill-switch state in status** — the `status` command's plain,
  rich, and JSON outputs now include a `kill_switch` field. When
  active, the rich/plain renderers show a bold-red `ACTIVE` row.

### Notes

- All additions are pure-additive; no behaviour changes for users
  who don't opt in to the new flags. No new runtime dependencies.

## [0.18.0] – 2026-04-30

### Added

- **`NO_COLOR` support** — when the env var is set (any value, per
  https://no-color.org) or stdout isn't a TTY, `doctor` and the plain
  `status` renderer fall back to ASCII glyphs (`OK` / `FAIL` / `--`)
  instead of UTF-8 symbols. Easier to grep, friendlier for log
  collectors and CI.
- **`connect --background`** — alias for `--detach`. Same semantics,
  the more obvious spelling for new users.
- **`connect --wait SECONDS`** — when used with `--detach`, blocks
  the supervisor for up to `SECONDS` until the tunnel interface
  appears. Useful in scripts that need the VPN actually up before
  proceeding (e.g. ``openconnect-saml connect work --detach --wait 30``).
- **`config diff FILE`** — produces a redacted unified diff between
  the active config and another TOML file. Secrets are stripped on
  both sides before diffing, so it's safe to share the output for
  troubleshooting.
- **`setup --advanced`** — adds prompts for client certificate path,
  on-connect / on-disconnect hooks, and a per-profile kill-switch
  flag. The default (non-advanced) wizard is unchanged for
  beginners.
- **`doctor` reports active sessions** — new "Active sessions" check
  shows how many recorded VPN sessions are currently live, with the
  profile names listed.

### Notes

- All additions are pure UX / scripting wins; no behaviour changes
  for users who don't opt in to the new flags. No new runtime
  dependencies.

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

## [0.7.1] – 2026-04-14

### Fixed

- The auth-target-URL probe (initial GET to discover redirects) used
  the AnyConnect-headered session, which some Cisco entry hosts
  reject with `404`. Switched to a plain `requests.Session` for that
  one probe — the AnyConnect headers come back for the real auth
  POST. Restores connect on gateways like Hungarian universities.
- AUR publish workflow rewritten end-to-end after multiple
  KSXGitHub-action regressions: direct `git push` instead of the
  third-party action, `--nosign` PKGBUILD, generates+commits
  `.SRCINFO` in the same atomic commit as the PKGBUILD bump,
  explicit git author config, no-op when nothing changed.

## [0.7.0] – 2026-04-14

### Added

- **`--useragent UA`** for `openconnect`'s outgoing connection. Some
  gateways gate access on UA string; this lets you spoof one without
  patching the wrapper.

## [0.6.1] – 2026-03-31

### Security

- Comprehensive second-pass audit (#10) covering credential handling,
  XML parsing, subprocess invocation, and TLS verification paths.

### Fixed

- Removed the duplicate PyPI publish step from `release.yml` —
  `publish.yml` is the canonical PyPI workflow, so the duplicate was
  racing and occasionally double-publishing.

## [0.6.0] – 2026-03-31

### Added

- **Split-tunnel routing**: `--route CIDR` (include) and `--no-route
  CIDR` (exclude) on top of openconnect's own routing. Useful when
  you want only the corporate /16 to go through the VPN and DNS to
  stay local.
- **Bitwarden TOTP provider** (`--totp-source bitwarden`,
  `--bw-item-id UUID`) via the `bw` CLI.
- **Desktop notifications** for connect/disconnect events via
  `notify-send` (Linux) / `osascript` (macOS) / Windows-toast.
- **`setup` wizard** — interactive first-run flow that walks the
  user through profile creation, credential storage, browser pick,
  TOTP provider, etc. The output gets written to the standard
  config file so subsequent `connect` runs are zero-arg.
- Misc security fixes from the (#9) audit pass.

## [0.5.0] – 2026-03-31

### Added

- **Multi-profile support** — `profiles add/list/show/remove`
  subcommands, `connect <profile-name>`, profile-specific config
  overrides. Replaces the single-server-per-config assumption.
- **Connection TUI** — live status display via `openconnect-saml
  status` (uptime, traffic, server, IP). `--watch` mode for
  refreshing display.
- **Shell completion** for bash / zsh / fish via `openconnect-saml
  completion`. Installed by default in the AUR package.

## [0.4.0] – 2026-03-31

### Added

- **2FAuth TOTP provider** (`--totp-source 2fauth`, `--2fauth-url`,
  `--2fauth-token`, `--2fauth-account-id`) — fetches the live OTP
  from a self-hosted [2FAuth](https://docs.2fauth.app/) instance via
  its REST API. Useful when you want TOTP centralised across
  devices without giving keyring access on each machine.

## [0.3.0] – 2026-03-31

### Added

- **`--browser chrome`** — Playwright-driven Chromium backend, runs
  headless without a DISPLAY. Provides the first FIDO2 / hardware
  key path that actually works in this wrapper.
- **`service` subcommand** — install/start/stop/status/logs for a
  systemd user-unit so the VPN can come up at login.
- **Auto-reconnect** (`--reconnect` / `--max-retries N`) — supervises
  the openconnect subprocess and reconnects with backoff when it
  drops.
- **FIDO2 / Yubikey support** (`[fido2]` extra, `python-fido2`).
  Only effective in browser modes that surface WebAuthn (Qt 6.7+,
  Chrome).

### Docs

- Modernised README — badges, feature table, collapsible sections,
  migration guide from `openconnect-sso`.

## [0.2.0] – 2026-03-31

### Added

- **Headless / CLI mode** (`--headless` / `--browser headless`) —
  no Qt, no Chromium, no DISPLAY needed. Drives the SAML form via
  `requests` + `lxml`. Falls back to a localhost callback server
  when scripted form-fill can't satisfy the IdP. Makes PyQt6 truly
  optional via a `[gui]` extra.

### Fixed

- Skip platform-specific tests on Windows that depended on POSIX-only
  modules (`termios`, `fcntl`, …).

## [0.1.1] – 2026-03-30

### CI

- Final security review and CI/CD pipeline pass (#4): integration
  tests run on Linux + macOS, switched lint/install plumbing to
  the standard `pip` flow, Linux jobs install `libegl1` for the
  PyQt6 import-time check.

## [0.1.0] – 2026-03-30

Initial public release of the maintained fork.

### Foundation

- Combines features from
  [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso)
  and [kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).
- Initial SSL legacy renegotiation support, robust TOTP handling,
  better error messages, configurable timeouts, on-connect scripts,
  window-size config (#1, #2, #3).
- AUR PKGBUILD ships from day one.
- Published to PyPI as `openconnect-saml`.
