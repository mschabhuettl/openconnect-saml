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

### TOTP / Password

Credentials are stored in the system keyring. On first use, you'll be prompted for your password and optional TOTP secret. You can also set them directly:

```bash
# Password is prompted interactively and saved to keyring
# TOTP secret can be configured in the keyring as well
```

If keyring is unavailable (e.g., headless server), passwords are kept in memory for the session.

## Credits

Based on [vlaci/openconnect-sso](https://github.com/vlaci/openconnect-sso) by László Vaskó, with improvements from [kowyo/openconnect-lite](https://github.com/kowyo/openconnect-lite).

## License

[GPL-3.0](LICENSE)
