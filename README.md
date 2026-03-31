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

Use Playwright-based Chromium instead of Qt WebEngine:

```bash
# Visible Chrome window
openconnect-saml --server vpn.example.com --browser chrome

# Headless Chrome (no display needed)
openconnect-saml --server vpn.example.com --browser headless
```

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
--totp-source SOURCE    # TOTP provider: local, 2fauth, or bitwarden
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
