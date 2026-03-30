# openconnect-saml

OpenConnect wrapper supporting **Azure AD / SAML authentication** for Cisco AnyConnect SSL-VPNs.

Modernized fork based on [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) with improvements from [kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).

## Features

- SAML / Azure AD authentication via embedded Qt WebEngine browser
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
- Qt6 WebEngine (provided by PyQt6)

## Installation

```bash
# Recommended: install as isolated tool
uv tool install openconnect-saml

# Or via pip
pip install openconnect-saml
```

## Usage

```bash
# Connect to a VPN server
openconnect-saml --server vpn.example.com

# With a specific user group
openconnect-saml --server vpn.example.com/usergroup

# Use AnyConnect profile
openconnect-saml --profile /opt/cisco/anyconnect/profile

# Authentication only (output cookie)
openconnect-saml --server vpn.example.com --authenticate

# Without sudo (for --script-tun)
openconnect-saml --server vpn.example.com --no-sudo -- --script-tun

# With CSD hostscan wrapper
openconnect-saml --server vpn.example.com --csd-wrapper /path/to/csd-wrapper.sh

# Reset saved credentials
openconnect-saml --user user@example.com --reset-credentials
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
