# openconnect-saml

OpenConnect wrapper supporting **Azure AD / SAML authentication** for Cisco AnyConnect SSL-VPNs.

Modernized fork based on [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) with improvements from [kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).

## Features

- SAML / Azure AD authentication via embedded Qt WebEngine browser **or headless CLI mode**
- **Headless mode**: No display/GUI required — works on servers, containers, and SSH sessions
- Automatic form-filling for username, password, and TOTP
- Password stored in system keyring (with in-memory fallback)
- TOTP secret configurable directly in config file
- Profile auto-detection from AnyConnect XML profiles
- Proxy support (SOCKS/HTTP)
- Client certificate handling (auto-fallback on cert-request)
- `--no-sudo` mode for use with `--script-tun`
- `--csd-wrapper` passthrough for CSD/hostscan support
- `--reset-credentials` to clear saved keyring entries
- Microsoft Authenticator number matching support
- Office365 "Stay signed in?" auto-dismiss
- Robust XML parsing (recovers from malformed responses)

## Requirements

- Python ≥ 3.10
- [OpenConnect](https://www.infradead.org/openconnect/) installed and in PATH
- Qt6 WebEngine (provided by PyQt6) — **only for GUI mode**

## Installation

```bash
# Headless mode (no GUI dependencies):
pip install openconnect-saml

# With GUI browser support:
pip install openconnect-saml[gui]

# Or via uv:
uv tool install openconnect-saml       # headless
uv tool install openconnect-saml[gui]   # with browser
```

## Usage

### GUI Mode (default)

```bash
# Connect to a VPN server
openconnect-saml --server vpn.example.com

# With a specific user group
openconnect-saml --server vpn.example.com/usergroup

# Use AnyConnect profile
openconnect-saml --profile /opt/cisco/anyconnect/profile
```

### Headless Mode (no display required)

Perfect for servers, containers, CI/CD, and SSH sessions:

```bash
# Automatic authentication (username/password/TOTP from keyring)
openconnect-saml --server vpn.example.com --headless --user user@example.com

# Authentication only — output cookie for scripting
openconnect-saml --server vpn.example.com --headless --user user@example.com --authenticate json
```

**How headless mode works:**

1. **Automatic**: Uses HTTP requests + form parsing to submit credentials (username, password, TOTP) without a browser. Works with standard Azure AD / Microsoft Online flows.
2. **Callback fallback**: If automatic auth fails (e.g., CAPTCHA, unsupported MFA), starts a local HTTP server and prints a URL. Open the URL in any browser (even on another machine), authenticate, and the callback captures the token.

### Docker Example

```dockerfile
FROM python:3.12-slim

RUN pip install openconnect-saml
RUN apt-get update && apt-get install -y openconnect && rm -rf /var/lib/apt/lists/*

# Run headless — no GUI needed
ENTRYPOINT ["openconnect-saml", "--headless"]
```

```bash
docker run -it --cap-add=NET_ADMIN --device=/dev/net/tun \
  vpn-client --server vpn.example.com --user user@example.com
```

### Server Deployment

On a headless server (no X11/Wayland):

```bash
# Install without GUI deps
pip install openconnect-saml

# First run — will prompt for password & TOTP secret, saves to keyring
openconnect-saml --server vpn.example.com --headless --user user@example.com

# Subsequent runs use saved credentials
openconnect-saml --server vpn.example.com --headless --user user@example.com
```

### More Options

```bash
# Without sudo (for --script-tun)
openconnect-saml --server vpn.example.com --no-sudo -- --script-tun

# With CSD hostscan wrapper
openconnect-saml --server vpn.example.com --csd-wrapper /path/to/csd-wrapper.sh

# Reset saved credentials
openconnect-saml --user user@example.com --reset-credentials

# SSL legacy mode (for older VPN appliances)
openconnect-saml --server vpn.example.com --ssl-legacy

# Custom timeout
openconnect-saml --server vpn.example.com --timeout 60
```

## Configuration

Config file: `$HOME/.config/openconnect-saml/config.toml`

```toml
[default_profile]
address = "vpn.example.com"
user_group = ""
name = "My VPN"

[credentials]
username = "user@example.com"

# Optional: run a command on disconnect
on_disconnect = ""
```

### Auto-fill rules

Custom auto-fill rules can be defined per URL pattern:

```toml
[auto_fill_rules]
"https://*" = [
    { selector = "input[type=email]", fill = "username" },
    { selector = "input[name=passwd]", fill = "password" },
    { selector = "input[id=idTxtBx_SAOTCC_OTC]", fill = "totp" },
]
```

#### Office365 "Stay signed in?" page

The default rules now auto-dismiss the "Stay signed in?" prompt. If you use custom `auto_fill_rules`, add these entries:

```toml
[[auto_fill_rules."https://*"]]
selector = "input[id=KmsiCheckboxField]"
action = "click"

[[auto_fill_rules."https://*"]]
selector = "input[id=idSIButton9]"
action = "click"
```

### TOTP / Password

Credentials are stored in the system keyring. On first use, you'll be prompted for your password and optional TOTP secret.

If keyring is unavailable (e.g., headless server), passwords are kept in memory for the session.

To clear stored credentials:

```bash
openconnect-saml --user user@example.com --reset-credentials
```

## Credits

Based on [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) by László Vaskó, with improvements from [kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).

## License

[GPL-3.0](LICENSE)
