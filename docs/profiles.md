# Profiles

Save named VPN configurations and switch between them. Profiles live in
the same TOML config file under `[profiles.<name>]` and are managed via
the `profiles` subcommand.

## Add / remove / rename

```bash
openconnect-saml profiles add work \
  --server vpn.company.com \
  --user user@company.com \
  --user-group employees

openconnect-saml profiles add lab \
  --server lab-vpn.company.com \
  --user admin

openconnect-saml profiles list
openconnect-saml profiles show work          # human-readable, redacted
openconnect-saml profiles show work --json
openconnect-saml profiles rename work office
openconnect-saml profiles remove lab
```

## Connect to a profile

```bash
openconnect-saml connect work
openconnect-saml connect work --browser chrome      # override
openconnect-saml connect work --server alt-vpn.example.com   # override server
```

The legacy form still works for one-shot connections:

```bash
openconnect-saml --server vpn.example.com --user user@example.com
```

## TOML structure

```toml
[profiles.work]
server = "vpn.company.com"
user_group = "employees"
name = "Work VPN"

[profiles.work.credentials]
username = "user@company.com"
totp_source = "1password"

[profiles.lab]
server = "lab-vpn.company.com"
name = "Lab VPN"

[profiles.lab.credentials]
username = "admin"
totp_source = "none"     # don't prompt for TOTP
```

## Export / import (JSON)

Share profiles across machines without secrets:

```bash
# Export one profile to a file
openconnect-saml profiles export work --file work.json

# Export all profiles to stdout
openconnect-saml profiles export > all-profiles.json

# Import (single or multi-profile payloads)
openconnect-saml profiles import work.json
openconnect-saml profiles import work.json --as office --force
cat work.json | openconnect-saml profiles import -
```

The export strips `password`, `totp`, `totp_secret`, and the 2fauth
`token`. Server URLs, usernames, TOTP source, split-tunnel routes, and
provider metadata are preserved.

## Export to NetworkManager (`.nmconnection`)

For the Ubuntu / GNOME VPN UI you can export a profile straight into
the `network-manager-openconnect` plugin format:

```bash
# Single profile to a file
openconnect-saml profiles export work \
  --format nmconnection -o work.nmconnection

# All profiles into a directory (one .nmconnection each)
openconnect-saml profiles export \
  --format nmconnection -o ./nm-export/

# Install system-wide
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

## Active profile

`active_profile` in the config file marks the most recently connected
profile (set automatically on successful connect). It's used by the
`status` command to label live connections.
