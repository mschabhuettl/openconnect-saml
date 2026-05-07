# Installation

`openconnect-saml` is published on PyPI and on the Arch User Repository.
The base install is headless (no GUI dependencies); GUI / browser /
hardware-key features are opt-in extras.

## PyPI

```bash
# Headless (no GUI dependencies, smallest install)
pip install openconnect-saml

# With Qt6 WebEngine browser
pip install "openconnect-saml[gui]"

# With Chrome/Chromium browser (Playwright)
pip install "openconnect-saml[chrome]"
playwright install chromium

# With FIDO2 / YubiKey support
pip install "openconnect-saml[fido2]"

# With status TUI (rich)
pip install "openconnect-saml[tui]"

# Everything
pip install "openconnect-saml[gui,chrome,fido2,tui]"
```

## Arch Linux (AUR)

```bash
yay -S openconnect-saml
# or
paru -S openconnect-saml
```

The AUR package follows upstream releases automatically (see
`.github/workflows/aur-publish.yml`). Hard-deps include `python-pyqt6`
+ `python-pyqt6-webengine` (for `--browser qt`); `optdepends`
surface what extras unlock additional backends:

| Optdepend | Unlocks |
|---|---|
| `python-rich` | rich-formatted `status` and the interactive `tui` |
| `python-playwright` | `--browser chrome` (Playwright headless Chromium). **Note:** `aur/playwright` is the **Node.js** library — make sure you install `aur/python-playwright` (#39). After install, run `playwright install chromium` once. |
| `python-fido2` | hardware-key (Yubikey / Nitrokey) auth in `--browser headless` mode |
| `keepassxc` | `--totp-source keepassxc` (provides the `keepassxc-cli`) |
| `bitwarden-cli` | `--totp-source bitwarden` (provides `bw`) |
| `1password-cli` | `--totp-source 1password` (provides `op`) |
| `pass` + `pass-otp` | `--totp-source pass` |

## Requirements

- **Python ≥ 3.10**
- [`openconnect`](https://www.infradead.org/openconnect/) in `$PATH`

  | Distro | Command |
  |---|---|
  | Debian / Ubuntu | `sudo apt install openconnect` |
  | Arch | `sudo pacman -S openconnect` |
  | Fedora | `sudo dnf install openconnect` |
  | macOS | `brew install openconnect` |

- **Linux only** for kill-switch (iptables) and systemd integration.
  Other features work cross-platform.

Run `openconnect-saml doctor` after installing to verify the
environment — it checks the `openconnect` binary, sudo/doas, the TUN
device, Python deps, the keyring backend, and (optionally) DNS / TLS
reachability of a `--server`.

## Docker

```dockerfile
FROM python:3.12-slim
RUN pip install openconnect-saml \
 && apt-get update && apt-get install -y openconnect \
 && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["openconnect-saml", "--headless"]
```

```bash
docker run -it --cap-add=NET_ADMIN --device=/dev/net/tun \
  vpn-client --server vpn.example.com --user user@example.com
```

## From source

```bash
git clone https://github.com/mschabhuettl/openconnect-saml
cd openconnect-saml
make dev          # uv sync --dev
make test         # pytest
make lint         # ruff check + format check
```

See [development.md](development.md) for contributor setup.
