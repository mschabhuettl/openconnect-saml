<h1 align="center">openconnect-saml</h1>

<p align="center">
  <strong>OpenConnect wrapper with Azure AD / SAML SSO support for Cisco AnyConnect VPNs.</strong>
</p>

<p align="center">
  <a href="https://github.com/mschabhuettl/openconnect-saml/actions"><img src="https://img.shields.io/github/actions/workflow/status/mschabhuettl/openconnect-saml/test.yml?branch=main&label=CI" alt="CI"></a>
  <a href="https://pypi.org/project/openconnect-saml/"><img src="https://img.shields.io/pypi/v/openconnect-saml" alt="PyPI"></a>
  <a href="https://aur.archlinux.org/packages/openconnect-saml"><img src="https://img.shields.io/aur/version/openconnect-saml" alt="AUR"></a>
  <a href="https://pypi.org/project/openconnect-saml/"><img src="https://img.shields.io/pypi/pyversions/openconnect-saml" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/mschabhuettl/openconnect-saml" alt="License"></a>
</p>

Drives the SAML/SSO authentication flow against Cisco AnyConnect
gateways and hands the resulting cookie to `openconnect`. Supports
Azure AD, ADFS, and most enterprise IdPs out of the box; works with
Yubikey / Nitrokey hardware keys, Duo, Microsoft Authenticator, and
TOTP from your password manager.

Maintained fork of [`vlaci/openconnect-sso`](https://github.com/vlaci/openconnect-sso),
combining work from [`kowyo/openconnect-lite`](https://github.com/kowyo/openconnect-lite).

## Install

```bash
pip install "openconnect-saml[gui]"        # Qt browser
pip install "openconnect-saml[chrome]"     # Chromium / Playwright
pip install  openconnect-saml              # Headless only
```

Arch: `yay -S openconnect-saml`. Requires Python ≥ 3.10 and
`openconnect` in `$PATH`. See
**[docs/installation.md](docs/installation.md)** for Docker, build
from source, and system-deps per distro.

## Quick start

```bash
# Interactive setup — server, username, TOTP, browser, auto-reconnect
openconnect-saml setup

# Connect to a saved profile
openconnect-saml connect work

# Or one-shot, no profile
openconnect-saml --server vpn.example.com --user user@example.com
```

Headless (servers, containers, CI):

```bash
openconnect-saml --server vpn.example.com --headless --user user@example.com
```

## Features

- **Three browser backends** — Qt6 WebEngine, Chromium via Playwright,
  or full headless. Hardware-key WebAuthn works in `--browser chrome`
  out of the box. With `--chrome-channel chrome|msedge` Playwright
  uses your system-installed Chrome / Edge instead of downloading
  its own bundled Chromium. See [docs/browsers.md](docs/browsers.md).
- **Seven TOTP providers** — local keyring,
  [2FAuth](https://docs.2fauth.app), Bitwarden, 1Password, pass,
  KeePassXC, plus `prompt` (type the 6-digit code from your phone
  every connect, store nothing), or `--no-totp` to skip entirely.
  See [docs/authentication.md](docs/authentication.md).
- **Microsoft Entra (Azure AD)** scripted in headless mode —
  username + password + TOTP fully driven via HTTPS. Federated
  tenants get an experimental ADFS / WS-Trust 2005 path; non-scriptable
  flows (FIDO2-only, push-MFA) surface a clear error pointing at
  `--browser chrome`.
- **`--auth-script PATH`** escape hatch for IdPs the built-in flow
  can't drive (in-house SSO, custom MFA). Your script gets the SSO
  endpoint + username on argv, password on stdin, prints the cookie
  to stdout. Thanks @derkarnold.
- **Multi-profile** — save / list / rename / export / import named
  VPN configs. Includes export to NetworkManager's `.nmconnection`
  format for the Ubuntu / GNOME VPN UI.
  See [docs/profiles.md](docs/profiles.md).
- **Auto-reconnect** with exponential back-off, optional cap.
  [`operations.md`](docs/operations.md#auto-reconnect)
- **Kill-switch** — iptables-based, session or persistent, with
  DNS / LAN allow-listing. [`networking.md`](docs/networking.md#kill-switch-linux--iptables)
- **systemd integration** — install a per-server unit; `service start`
  / `stop` / `status` / `logs`. [`operations.md`](docs/operations.md#systemd-service)
- **Connection history & stats** — JSONL audit log, aggregated
  summaries (`history stats`), JSON output for monitoring.
  [`operations.md`](docs/operations.md#connection-history)
- **Diagnostics** — `doctor` checks Python / openconnect / sudo / TUN
  / dependencies / keyring / DNS / TLS / SAML endpoint.
  [`diagnostics.md`](docs/diagnostics.md)

## Documentation

The [docs/](docs/) directory has a topic-per-file reference. Start
with [docs/README.md](docs/README.md) for the index.

| Topic | Where |
|---|---|
| Installation, Docker, system deps | [docs/installation.md](docs/installation.md) |
| Browser backends + minimal GUI | [docs/browsers.md](docs/browsers.md) |
| TOTP providers + FIDO2 + credentials | [docs/authentication.md](docs/authentication.md) |
| Profiles + NetworkManager export | [docs/profiles.md](docs/profiles.md) |
| Split-tunnel + kill-switch + proxy | [docs/networking.md](docs/networking.md) |
| Reconnect, systemd, status, history | [docs/operations.md](docs/operations.md) |
| Config file + `setup` + `config` subcommand | [docs/configuration.md](docs/configuration.md) |
| `doctor`, troubleshooting, exit codes | [docs/diagnostics.md](docs/diagnostics.md) |
| Full CLI reference (every flag) | [docs/cli-reference.md](docs/cli-reference.md) |
| Contributor setup + release flow | [docs/development.md](docs/development.md) |
| Migrating from `openconnect-sso` | [docs/migration.md](docs/migration.md) |

## Links

| Resource | URL |
|---|---|
| **PyPI** | <https://pypi.org/project/openconnect-saml/> |
| **AUR** | <https://aur.archlinux.org/packages/openconnect-saml> |
| **Releases** | <https://github.com/mschabhuettl/openconnect-saml/releases> |
| **Issues** | <https://github.com/mschabhuettl/openconnect-saml/issues> |
| **Changelog** | [CHANGELOG.md](CHANGELOG.md) |
| **License** | [GPL-3.0](LICENSE) |

## Credits

**Upstream / origin**

- [László Vaskó (vlaci)](https://github.com/vlaci) — original
  [`openconnect-sso`](https://github.com/vlaci/openconnect-sso)
- [Kowyo](https://github.com/kowyo) —
  [`openconnect-lite`](https://github.com/kowyo/openconnect-lite)
  modernization

**Recent contributors**

- [@derkarnold](https://github.com/derkarnold) — `--auth-script`
  pluggable authentication (#29, v0.23.0)
- [@salty-flower](https://github.com/salty-flower) — root-cause
  diagnosis of the PyQt 6.11 WebAuthn slot-signature crash (#24,
  v0.21.0)
- [@kobuki](https://github.com/kobuki) — `--no-cert-check` /
  self-signed gateway report driving the v0.22.0 + v0.22.2 cert
  fixes and the console-only Microsoft Entra path in v0.22.4 (#19)
- [@OmarHawk](https://github.com/OmarHawk) — `--allowed-hosts`
  whitelist proposal (#11, v0.20.0), `--useragent` (#12, v0.7.0),
  openconnect passthrough (#13, v0.7.0), MFA discussion that
  shaped the chrome / qt / headless three-way split (#17)
- [@BBKmsZrd](https://github.com/BBKmsZrd) — Yubikey / Nitrokey
  hardware-token reports + iterative debug-log triage (#21, #24)
- [@cnekmp](https://github.com/cnekmp) — `sso-v2-login` parser
  regression report driving the namespaced-fields + form fallback
  (#20, v0.8.1)
- [@mdesantis](https://github.com/mdesantis) — minimal GUI proposal
  + NetworkManager `.nmconnection` export request (#22, v0.8.x)

**Everyone else** who's filed an issue, tested a release candidate,
or pasted a debug log — thank you. See the full
[contributors graph](https://github.com/mschabhuettl/openconnect-saml/graphs/contributors).

---

<p align="center">
  <a href="https://www.buymeacoffee.com/mschabhuettl" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="48"></a>
</p>
