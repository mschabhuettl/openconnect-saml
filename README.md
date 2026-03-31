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
| 🔒 **Keyring** | Credentials stored securely (with in-memory fallback) |
| 📱 **MFA Support** | TOTP, Microsoft Authenticator number matching |
| 🔐 **FIDO2/YubiKey** | Hardware security key support for WebAuthn challenges |
| 🛡️ **Security** | XXE protection, no credential logging, safe config permissions |
| 🔄 **Auto-Reconnect** | Automatic re-authentication and reconnection on VPN drops |
| ⚙️ **Systemd Service** | Install as a persistent system service with one command |
| 🌐 **Proxy** | SOCKS and HTTP proxy support |
| 📜 **Certificates** | Client certificate handling with auto-fallback |
| 🐳 **Docker-ready** | Headless mode for containerized deployments |

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

# Arch Linux (AUR)
yay -S openconnect-saml
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

### Advanced Options

```bash
--headless              # No browser, terminal-only authentication
--browser BACKEND       # Browser backend: qt, chrome, headless
--reconnect             # Auto-reconnect on VPN drops
--max-retries N         # Max reconnection attempts (default: unlimited)
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

## 🙏 Credits

- [László Vaskó (vlaci)](https://github.com/vlaci) — original [openconnect-sso](https://github.com/vlaci/openconnect-sso)
- [Kowyo](https://github.com/kowyo) — [openconnect-lite](https://github.com/kowyo/openconnect-lite) modernization
- Community contributors for issues, PRs, and testing

## 📄 License

[GPL-3.0](LICENSE)
