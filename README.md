<h1 align="center">
  🔐 openconnect-saml
</h1>

<p align="center">
  <strong>OpenConnect wrapper with Azure AD / SAML authentication for Cisco AnyConnect VPNs</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/openconnect-saml/"><img src="https://img.shields.io/pypi/v/openconnect-saml?color=blue&label=PyPI" alt="PyPI"></a>
  <a href="https://aur.archlinux.org/packages/openconnect-saml"><img src="https://img.shields.io/aur/version/openconnect-saml?color=1793D1&label=AUR" alt="AUR"></a>
  <a href="https://github.com/mschabhuettl/openconnect-saml/actions"><img src="https://img.shields.io/github/actions/workflow/status/mschabhuettl/openconnect-saml/test.yml?label=CI" alt="CI"></a>
  <a href="https://github.com/mschabhuettl/openconnect-saml/blob/main/LICENSE"><img src="https://img.shields.io/github/license/mschabhuettl/openconnect-saml?color=green" alt="License"></a>
  <a href="https://pypi.org/project/openconnect-saml/"><img src="https://img.shields.io/pypi/pyversions/openconnect-saml" alt="Python"></a>
  <a href="https://pypi.org/project/openconnect-saml/"><img src="https://img.shields.io/pypi/dm/openconnect-saml?color=orange&label=Downloads" alt="Downloads"></a>
</p>

<p align="center">
  <em>Maintained fork of <a href="https://github.com/vlaci/openconnect-sso">vlaci/openconnect-sso</a> with improvements from <a href="https://github.com/kowyo/openconnect-lite">kowyo/openconnect-lite</a></em>
</p>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🖥️ **GUI Mode** | Embedded Qt6 WebEngine browser with auto-fill |
| 🌐 **Chrome Browser** | Playwright-based Chromium backend — headless or visible |
| 🤖 **Headless Mode** | No display needed — works on servers, containers, SSH |
| 🔑 **Auto-Login** | Username, password, and TOTP auto-injection |
| 🌍 **2FAuth** | Fetch TOTP from a remote [2FAuth](https://docs.2fauth.app/) instance |
| 🔒 **Keyring** | Credentials stored securely (with in-memory fallback) |
| 📱 **MFA Support** | TOTP, Microsoft Authenticator number matching |
| 🔐 **FIDO2/YubiKey** | Hardware security key support for WebAuthn challenges |
| 🛡️ **Security** | XXE protection, no credential logging, safe config permissions |
| 🔄 **Auto-Reconnect** | Automatic re-authentication and reconnection on VPN drops |
| ⚙️ **Systemd Service** | Install as a persistent system service with one command |
| 🌐 **Proxy** | SOCKS and HTTP proxy support |
| 📜 **Certificates** | Client certificate handling with auto-fallback |
| 🐳 **Docker-ready** | Headless mode for containerized deployments |
| 👤 **Multi-Profile** | Save and switch between named VPN configurations |
| 📊 **Status TUI** | Live connection status with traffic stats (`rich` optional) |
| ⌨️ **Shell Completion** | Tab completion for bash, zsh, and fish |
| 🔀 **Split-Tunnel** | Route only specific subnets through the VPN |
| 🔑 **Bitwarden TOTP** | Fetch TOTP from Bitwarden CLI (`bw`) |
| 🔔 **Notifications** | Desktop notifications for VPN events |
| 🧙 **Setup Wizard** | Interactive `setup` command for easy configuration |

## 📦 Installation

```bash
# Headless (no GUI dependencies)
pip install openconnect-saml

# With GUI browser (Qt6 WebEngine)
pip install "openconnect-saml[gui]"

# With Chrome/Chromium browser (Playwright)
pip install "openconnect-saml[chrome]"
playwright install chromium

# With FIDO2/YubiKey support
pip install "openconnect-saml[fido2]"

# With connection status TUI (rich)
pip install "openconnect-saml[tui]"

# All extras (GUI + Chrome + FIDO2 + TUI)
pip install "openconnect-saml[gui,chrome,fido2,tui]"

# Arch Linux (AUR)
yay -S openconnect-saml
# or
paru -S openconnect-saml
```

> **Requires:** Python ≥ 3.10 and [OpenConnect](https://www.infradead.org/openconnect/) in PATH

## 🚀 Quick Start

```bash
# GUI mode (default)
openconnect-saml --server vpn.example.com --user user@domain.com

# Headless mode (servers, containers, SSH)
openconnect-saml --server vpn.example.com --user user@domain.com --headless
```

## 📖 Usage

### GUI Mode

```bash
openconnect-saml --server vpn.example.com
openconnect-saml --server vpn.example.com/usergroup
openconnect-saml --profile /opt/cisco/anyconnect/profile
```

### Headless Mode

No display server required — perfect for servers, CI/CD, and containers:

```bash
# Auto-authenticate with saved credentials
openconnect-saml --server vpn.example.com --headless --user user@example.com

# Output auth cookie for scripting
openconnect-saml --server vpn.example.com --headless --authenticate json
```

**How it works:**
1. **Auto**: HTTP requests + form parsing → submits credentials without a browser
2. **Fallback**: If auto-auth fails (CAPTCHA, unsupported MFA) → prints URL + starts local callback server → authenticate in any browser

### Chrome/Chromium Browser

Use Playwright-based Chromium instead of Qt WebEngine. Both backends
support YubiKey/Nitrokey/WebAuthn and Duo/Microsoft Authenticator since
v0.8.2 (Qt-WebEngine ≥ 6.7 required for the Qt backend). Chrome remains
the recommended fallback if you hit Qt-platform-specific quirks.

```bash
# Visible Chrome window
openconnect-saml --server vpn.example.com --browser chrome

# Saved profile with Chrome override
openconnect-saml connect work --browser chrome

# Headless Chrome (no display needed)
openconnect-saml --server vpn.example.com --browser headless
```

### Minimal Profile GUI

For a small Cisco Secure Client-like launcher around saved profiles:

```bash
openconnect-saml gui
```

The GUI lists saved profiles, starts `connect <profile> --browser chrome`,
shows output, and can terminate the VPN process. It is intentionally minimal;
advanced options still live in the CLI.

### Auto-Reconnect

Keep the VPN alive — automatically re-authenticates and reconnects on drops:

```bash
# Unlimited retries with backoff (30s, 60s, 120s, 300s)
openconnect-saml --server vpn.example.com --headless --reconnect

# Limit to 5 reconnection attempts
openconnect-saml --server vpn.example.com --headless --reconnect --max-retries 5
```

### Systemd Service

Install as a persistent system service:

```bash
# Install and enable
sudo openconnect-saml service install --server vpn.example.com --user user@domain.com

# Manage
sudo openconnect-saml service start --server vpn.example.com
sudo openconnect-saml service stop --server vpn.example.com
openconnect-saml service status
openconnect-saml service logs --server vpn.example.com

# Remove
sudo openconnect-saml service uninstall --server vpn.example.com
```

### FIDO2/YubiKey

Hardware security key support for WebAuthn challenges during SAML authentication:

```bash
# FIDO2 is detected automatically during auth flows
# When a WebAuthn challenge is encountered:
# → Terminal prompt: "Touch your security key..."
# → PIN prompt if required
pip install "openconnect-saml[fido2]"
```

### 2FAuth TOTP Provider

Fetch TOTP codes from a [2FAuth](https://docs.2fauth.app/) instance instead of storing secrets locally:

```bash
# Via CLI flags
openconnect-saml --server vpn.example.com --headless --user user@domain.com \
  --totp-source 2fauth \
  --2fauth-url https://2fauth.example.com \
  --2fauth-token YOUR_PERSONAL_ACCESS_TOKEN \
  --2fauth-account-id 42

# Or via config file (~/.config/openconnect-saml/config.toml)
```

```toml
[credentials]
username = "user@example.com"
totp_source = "2fauth"

[2fauth]
url = "https://2fauth.example.com"
token = "eyJ0eXAiOiJKV1QiLC..."
account_id = 42
```

**Setup:**
1. Install [2FAuth](https://docs.2fauth.app/) and add your VPN TOTP account
2. Create a Personal Access Token in 2FAuth (Settings → OAuth → Personal Access Tokens)
3. Note the account ID (visible in the URL when editing the account, or via API)
4. Configure openconnect-saml with `--totp-source 2fauth` or `totp_source = "2fauth"` in config

> ⚠️ HTTPS is strongly recommended for the 2FAuth URL. HTTP connections will trigger a warning.

### Bitwarden TOTP Provider

Fetch TOTP codes from your Bitwarden vault via the `bw` CLI:

```bash
# Via CLI flags
openconnect-saml --server vpn.example.com --headless --user user@domain.com \
  --totp-source bitwarden \
  --bw-item-id YOUR_VAULT_ITEM_UUID

# Or via config file (~/.config/openconnect-saml/config.toml)
```

```toml
[credentials]
username = "user@example.com"
totp_source = "bitwarden"

[bitwarden]
item_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

**Setup:**
1. Install the [Bitwarden CLI](https://bitwarden.com/help/cli/) (`bw`)
2. Log in: `bw login` and unlock: `bw unlock` → export `BW_SESSION`
3. Find your item ID: `bw list items --search "VPN"` → note the `id` field
4. Configure: `--totp-source bitwarden --bw-item-id <uuid>`

### Split-Tunnel Routing

Route only specific subnets through the VPN (split-tunneling):

```bash
# Include specific routes
openconnect-saml connect work --route 10.0.0.0/8 --route 172.16.0.0/12

# Exclude routes (bypass VPN for these)
openconnect-saml connect work --no-route 192.168.0.0/16

# Combine both
openconnect-saml connect work --route 10.0.0.0/8 --no-route 10.0.99.0/24
```

Or configure per-profile:
```toml
[profiles.work]
server = "vpn.company.com"
routes = ["10.0.0.0/8", "172.16.0.0/12"]
no_routes = ["192.168.0.0/16"]
```

### Desktop Notifications

Get notified about VPN events (connect, disconnect, reconnect, errors):

```bash
# Enable via CLI
openconnect-saml connect work --notify

# Or in config
notifications = true
```

Supports: Linux (`notify-send`), macOS (`osascript`), fallback (terminal bell).

### Setup Wizard

Interactive configuration wizard for first-time setup:

```bash
openconnect-saml setup
```

Guides through: server URL, username, TOTP provider, browser mode, auto-reconnect, and notifications. Saves a named profile.

### Multi-Profile

Save named VPN configurations and switch between them:

```bash
# Add profiles
openconnect-saml profiles add work --server vpn.company.com --user user@company.com
openconnect-saml profiles add lab --server lab-vpn.company.com --user admin

# List profiles
openconnect-saml profiles list

# Connect to a profile
openconnect-saml connect work
openconnect-saml connect lab

# Override server from profile
openconnect-saml connect work --server alt-vpn.company.com

# Remove a profile
openconnect-saml profiles remove lab

# Legacy mode still works (backwards-compatible)
openconnect-saml --server vpn.example.com
```

Config file format:
```toml
[profiles.work]
server = "vpn.company.com"
user_group = "employees"
name = "Work VPN"

[profiles.work.credentials]
username = "user@company.com"
totp_source = "2fauth"

[profiles.lab]
server = "lab-vpn.company.com"
name = "Lab VPN"

[profiles.lab.credentials]
username = "admin"
```

### Connection Status

View live VPN connection status:

```bash
# One-shot status
openconnect-saml status

# Live-updating status (refreshes every 2s)
openconnect-saml status --watch
```

Install with rich for a formatted table display:
```bash
pip install "openconnect-saml[tui]"
```

### Shell Completion

```bash
# Generate completion scripts
openconnect-saml completion bash
openconnect-saml completion zsh
openconnect-saml completion fish

# Auto-install to default locations
openconnect-saml completion install
```

### Advanced Options

```bash
--headless              # No browser, terminal-only authentication
--browser BACKEND       # Browser backend: qt, chrome, headless
--totp-source SOURCE    # TOTP provider: local, 2fauth, bitwarden, 1password, pass, or none
--no-totp               # Skip the TOTP prompt entirely (alias for --totp-source none)
--2fauth-url URL        # 2FAuth instance URL
--2fauth-token TOKEN    # 2FAuth Personal Access Token
--2fauth-account-id ID  # 2FAuth account ID for VPN TOTP
--bw-item-id UUID       # Bitwarden vault item ID for TOTP
--reconnect             # Auto-reconnect on VPN drops
--max-retries N         # Max reconnection attempts (default: unlimited)
--route CIDR            # Include route in VPN tunnel (repeatable)
--no-route CIDR         # Exclude route from VPN tunnel (repeatable)
--notify                # Enable desktop notifications
--no-sudo               # Don't use sudo (for --script-tun)
--ssl-legacy            # Enable legacy SSL renegotiation
--csd-wrapper PATH      # CSD/hostscan wrapper script
--timeout SECONDS       # HTTP timeout (default: 30)
--window-size WxH       # Browser window size (default: 800x600)
--on-connect CMD        # Run command after VPN connects
--on-disconnect CMD     # Run command after VPN disconnects
--reset-credentials     # Clear saved keyring entries
--authenticate FORMAT   # Auth only, output cookie (json|shell)
--config FILE           # Override XDG config path (or set $OPENCONNECT_SAML_CONFIG)
```

### 🐳 Docker

```dockerfile
FROM python:3.12-slim
RUN pip install openconnect-saml && \
    apt-get update && apt-get install -y openconnect && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["openconnect-saml", "--headless"]
```

```bash
docker run -it --cap-add=NET_ADMIN --device=/dev/net/tun \
  vpn-client --server vpn.example.com --user user@example.com
```

## ⚙️ Configuration

Config file: `~/.config/openconnect-saml/config.toml`

```toml
[default_profile]
server = "vpn.example.com"
user_group = ""
name = "My VPN"

[credentials]
username = "user@example.com"

# Named profiles (optional)
[profiles.work]
server = "vpn.company.com"
user_group = "employees"
name = "Work VPN"

[profiles.work.credentials]
username = "user@company.com"
```

<details>
<summary><strong>Auto-fill Rules</strong></summary>

Custom rules per URL pattern:

```toml
[[auto_fill_rules."https://*"]]
selector = "input[type=email]"
fill = "username"

[[auto_fill_rules."https://*"]]
selector = "input[name=passwd]"
fill = "password"

[[auto_fill_rules."https://*"]]
selector = "input[id=idTxtBx_SAOTCC_OTC]"
fill = "totp"
```

</details>

<details>
<summary><strong>TOTP Configuration</strong></summary>

For automated TOTP, add your secret to the config:

```toml
[credentials]
username = "user@example.com"
# TOTP secret is stored in keyring on first use
# Or set via: openconnect-saml --user user@example.com (prompts for secret)
```

To clear stored credentials:
```bash
openconnect-saml --user user@example.com --reset-credentials
```

</details>

## 🔄 Migrating from openconnect-sso

```bash
# Replace openconnect-sso with openconnect-saml
pip uninstall openconnect-sso
pip install openconnect-saml

# Rename config directory
mv ~/.config/openconnect-sso ~/.config/openconnect-saml

# Same CLI, new name
openconnect-saml --server vpn.example.com
```

## 🛠️ Development

```bash
git clone https://github.com/mschabhuettl/openconnect-saml
cd openconnect-saml
pip install -e ".[dev]"
pytest -v
ruff check .
```

## 📎 Links

| Resource | URL |
|----------|-----|
| **GitHub** | [mschabhuettl/openconnect-saml](https://github.com/mschabhuettl/openconnect-saml) |
| **PyPI** | [pypi.org/project/openconnect-saml](https://pypi.org/project/openconnect-saml/) |
| **AUR** | [aur.archlinux.org/packages/openconnect-saml](https://aur.archlinux.org/packages/openconnect-saml) |
| **Releases** | [GitHub Releases](https://github.com/mschabhuettl/openconnect-saml/releases) |
| **Issues** | [Bug Tracker](https://github.com/mschabhuettl/openconnect-saml/issues) |
| **Changelog** | [CHANGELOG.md](https://github.com/mschabhuettl/openconnect-saml/blob/main/CHANGELOG.md) |
| **License** | [GPL-3.0](https://github.com/mschabhuettl/openconnect-saml/blob/main/LICENSE) |
| **Original** | [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) |

## 🙏 Credits

- [László Vaskó (vlaci)](https://github.com/vlaci) — original [openconnect-sso](https://github.com/vlaci/openconnect-sso)
- [Kowyo](https://github.com/kowyo) — [openconnect-lite](https://github.com/kowyo/openconnect-lite) modernization
- Community contributors for issues, PRs, and testing

## 📄 License

[GPL-3.0](LICENSE)

---

<a href="https://www.buymeacoffee.com/mschabhuettl" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" style="height: 60px !important;width: 217px !important;" ></a>

---

# openconnect-saml — v0.8.0 feature additions

The following sections document the six new features added in v0.8.0.
These are supplements to the main `README.md`; integrate them into the
appropriate sections of the main README.

---

## 1Password TOTP

Delegate TOTP generation to 1Password's `op` CLI. You'll need to be signed
in (`op signin` with an exported session token, or biometric/system
integration on desktop OSes).

```bash
openconnect-saml connect work \
    --totp-source 1password \
    --1password-item "vpn-work-mfa" \
    --1password-vault "Engineering"
```

Configuration equivalent:

```toml
[1password]
item = "vpn-work-mfa"       # UUID, name, or share URL
vault = "Engineering"        # optional — searches all vaults if omitted
account = "acme.1password.com"  # optional, for multi-account setups

[profiles.work.credentials]
totp_source = "1password"
```

## pass (password-store) TOTP

Uses the [`pass-otp`](https://github.com/tadfisher/pass-otp) extension.
Your password entry must contain a `otpauth://` or `totp://` URI.

```bash
openconnect-saml connect work \
    --totp-source pass \
    --pass-entry "vpn/work-totp"
```

Configuration:

```toml
[pass]
entry = "vpn/work-totp"

[profiles.work.credentials]
totp_source = "pass"
```

Requirements: the `pass` binary, the `pass-otp` extension, and an
unlocked GPG agent.

## Kill-switch (Linux / iptables)

Blocks every outbound connection except to the VPN server, loopback, and
`tun*`/`utun*`/`ppp*` tunnels. Connection replies are allowed via
conntrack `ESTABLISHED,RELATED`. Optionally allowlist DNS resolvers and
RFC1918 LAN ranges.

**One-shot (auto-clears on disconnect):**

```bash
openconnect-saml connect work --kill-switch \
    --ks-allow-dns 1.1.1.1 --ks-allow-dns 9.9.9.9 \
    --ks-allow-lan
```

**Standalone (persists until explicitly disabled):**

```bash
sudo openconnect-saml killswitch enable -s vpn.example.com \
    --ks-allow-dns 1.1.1.1
sudo openconnect-saml killswitch status
sudo openconnect-saml killswitch disable
```

Persistent configuration:

```toml
[kill_switch]
enabled = true
allow_lan = false
ipv6 = true
dns_servers = ["1.1.1.1", "9.9.9.9"]
```

**Safety notes**

- iptables only (Linux); other platforms return a clear
  `KillSwitchNotSupported` error.
- The chain `OPENCONNECT_SAML_KILLSWITCH` is the only thing installed;
  removal is idempotent via `killswitch disable`.
- If the CLI crashes and the chain is stuck, `iptables -F
  OPENCONNECT_SAML_KILLSWITCH && iptables -X OPENCONNECT_SAML_KILLSWITCH`
  will remove it.
- The session-based `--kill-switch` flag automatically tears down on
  disconnect. The persistent form (configured in `[kill_switch]` or via
  `killswitch enable`) stays up until explicitly disabled.

## Profile export / import

Share profiles across machines without secrets:

```bash
openconnect-saml profiles export work --file work.json
openconnect-saml profiles export > all-profiles.json
openconnect-saml profiles import work.json
openconnect-saml profiles import work.json --as office --force
cat work.json | openconnect-saml profiles import -
```

The export strips `password`, `totp`, `totp_secret`, and the 2fauth
`token` — usernames, server URLs, TOTP source, and split-tunnel routes
are preserved. New companion commands:

```bash
openconnect-saml profiles rename old-name new-name
openconnect-saml profiles show work --json   # redacted view
```

### NetworkManager (`.nmconnection`) export

For the Ubuntu / GNOME VPN UI you can export a profile straight into the
`network-manager-openconnect` plugin format:

```bash
# Single profile to a file
openconnect-saml profiles export work \
    --format nmconnection -o work.nmconnection

# All profiles into a directory (one .nmconnection each)
openconnect-saml profiles export \
    --format nmconnection -o ./nm-export/

# Install system-wide (requires root)
sudo cp work.nmconnection /etc/NetworkManager/system-connections/
sudo chmod 600 /etc/NetworkManager/system-connections/work.nmconnection
sudo nmcli connection reload
```

The generated file uses
`org.freedesktop.NetworkManager.openconnect`, sets the gateway, the
auth-group (`usergroup=`), and a stable UUID derived from the profile
name (re-exporting overwrites the same NM connection rather than
duplicating). Secrets are not written; SAML/SSO authentication still
happens at connect time via the openconnect plugin.

## `config` subcommand

Inspect and validate the configuration file:

```bash
openconnect-saml config path
openconnect-saml config show            # TOML, secrets redacted
openconnect-saml config show --json
openconnect-saml config validate        # schema + semantic checks
openconnect-saml config edit            # opens $EDITOR
```

`validate` catches: TOML syntax errors, missing `server` on a profile,
unresolvable `active_profile`, missing `[2fauth]`/`[bitwarden]` for
profiles that reference them, invalid CIDRs in `routes`/`no_routes`, and
overly-permissive file modes.

## `doctor` command

One-shot system diagnostics. Exit code: 0 = all OK, 1 = at least one
failure, 2 = at least one warning.

```bash
openconnect-saml doctor
openconnect-saml doctor -s vpn.example.com   # also test DNS + TCP
```

Checks include: Python version ≥ 3.10, `openconnect` binary,
sudo/doas, `/dev/net/tun`, core deps (attrs, keyring, lxml, pyotp,
requests, structlog, toml), optional deps (PyQt6, playwright, fido2,
rich), keyring backend, config dir + permissions, credential env-var
presence, DNS resolution + TCP reachability of a provided server, and
whether the kill-switch is currently active.

## Connection history

A lightweight audit log of VPN sessions, written to
`$XDG_STATE_HOME/openconnect-saml/history.jsonl` (owner-read 0o600,
rotated at 512 KiB). One JSON object per line.

```bash
openconnect-saml history show           # human-readable, newest first
openconnect-saml history show -n 20     # limit to 20 entries
openconnect-saml history show --json
openconnect-saml history clear
openconnect-saml history path
```

Events logged: `connected`, `disconnected` (with duration),
`reconnecting` (with attempt number and backoff delay), `error`.

**Privacy / security**

- Only metadata: timestamp, event type, server URL, profile name,
  username, duration, free-text message.
- Never logs passwords, tokens, TOTP codes, or session cookies.
- Enabled by default. Disable per session with `--no-history` or
  globally with `connection_history = false` in config.

## Exit codes (reference)

| Code | Meaning                                            |
|-----:|----------------------------------------------------|
|   0  | Success                                            |
|   1  | Generic failure                                    |
|   2  | Platform not supported / browser terminated       |
|   3  | Authentication response missing expected fields   |
|   4  | HTTP error during authentication                   |
|  17  | No AnyConnect profile found                        |
|  18  | No AnyConnect profile selected                     |
|  19  | Invalid arguments                                  |
|  20  | No superuser tool / not running as Administrator   |
|  21  | 2FAuth TOTP config missing                         |
|  22  | Bitwarden TOTP config missing                      |
|  23  | 1Password TOTP config missing                      |
|  24  | pass TOTP config missing                           |
|  130 | Interrupted (Ctrl-C)                               |
