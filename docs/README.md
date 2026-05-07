# Documentation

Detailed reference for `openconnect-saml`. The top-level
[README on GitHub](https://github.com/mschabhuettl/openconnect-saml#readme)
covers a quick install + the most common flows; this directory
covers each topic in depth.

## By topic

- **[Installation](installation.md)** — pip, AUR, Docker, system
  requirements, build from source.
- **[Browser backends](browsers.md)** — headless / Qt / Chrome, when
  to use which, GUI launcher.
- **[Authentication](authentication.md)** — credentials, keyring, all
  TOTP providers (`local`, 2FAuth, Bitwarden, 1Password, pass,
  KeePassXC, `prompt` for "type-by-hand-every-time"), FIDO2
  hardware keys, `--auth-script` escape hatch, federated MS Entra
  (ADFS / WS-Trust) flow.
- **[Profiles](profiles.md)** — multi-profile management, JSON export
  / import, NetworkManager `.nmconnection` export.
- **[Networking](networking.md)** — split-tunnel routing, kill-switch,
  proxy, SSL legacy mode.
- **[Operations](operations.md)** — auto-reconnect, systemd service,
  desktop notifications, live status, connection history, on-connect
  / on-disconnect hooks.
- **[Configuration](configuration.md)** — config file structure,
  `setup` wizard, `config` subcommand, `--config FILE` override.
- **[Diagnostics](diagnostics.md)** — `doctor` subcommand, common
  error fixes, exit codes.
- **[CLI reference](cli-reference.md)** — every flag and subcommand.
- **[Development](development.md)** — contributor setup, project
  layout, release flow.
- **[Migration](migration.md)** — from `openconnect-sso`,
  `openconnect-lite`, or Cisco Secure Client.

## Quick links

| What I want to do | See |
|---|---|
| Install and run for the first time | [installation.md](installation.md) → [configuration.md#setup-wizard](configuration.md#setup-wizard) |
| Use a hardware key (Yubikey / Nitrokey) | [authentication.md#fido2-hardware-security-keys](authentication.md#fido2-hardware-security-keys) |
| Type the TOTP code from my phone every connect | [authentication.md#prompt-type-the-code-by-hand-every-connect](authentication.md#prompt-type-the-code-by-hand-every-connect) |
| Plug in a custom IdP / federated MS Entra | [authentication.md#external-authentication-script](authentication.md#external-authentication-script) |
| Skip Playwright's Chromium download (use system Chrome) | [authentication.md#saving-the-150-mb-chromium-download](authentication.md#saving-the-150-mb-chromium-download) |
| Connect from a server / container without a display | [browsers.md#headless](browsers.md#headless) |
| Save multiple VPN configurations | [profiles.md](profiles.md) |
| Send a profile to the Ubuntu VPN UI | [profiles.md#export-to-networkmanager-nmconnection](profiles.md#export-to-networkmanager-nmconnection) |
| Block all non-VPN traffic | [networking.md#kill-switch](networking.md#kill-switch) |
| Keep the VPN alive across drops | [operations.md#auto-reconnect](operations.md#auto-reconnect) |
| Run as a system service | [operations.md#systemd-service](operations.md#systemd-service) |
| Debug a connection problem | [diagnostics.md](diagnostics.md) |
| Find a flag I half-remember | [cli-reference.md](cli-reference.md) |
| Migrate from `openconnect-sso` | [migration.md](migration.md) |
