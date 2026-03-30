# openconnect-saml (AUR)

Arch Linux AUR package for [openconnect-saml](https://github.com/mschabhuettl/openconnect-saml) — an OpenConnect wrapper with Azure AD (SAML) SSO support for Cisco SSL-VPNs.

## Installation

### With an AUR helper (recommended)

```bash
# yay
yay -S openconnect-saml

# paru
paru -S openconnect-saml
```

### Manual build

```bash
git clone https://aur.archlinux.org/openconnect-saml.git
cd openconnect-saml
makepkg -si
```

## Usage

After installation, run:

```bash
openconnect-saml
```

See the [main README](https://github.com/mschabhuettl/openconnect-saml#readme) for configuration and usage details.

## Dependencies

- `openconnect` — the underlying VPN client
- `python-pyqt6` + `python-pyqt6-webengine` — for the SAML browser window
- Various Python libraries (attrs, keyring, structlog, etc.)

All dependencies are available in the official Arch repositories.

## License

GPL-3.0-or-later
