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
# Per-profile overrides (v0.11.0+). All optional; unset = use top-level config.
browser = "chrome"                   # qt | chrome | headless
notify = true                         # desktop notifications
on_connect = "/usr/local/bin/route-add"
on_disconnect = "/usr/local/bin/route-cleanup"

[profiles.work.credentials]
username = "user@company.com"
totp_source = "1password"

# Per-profile kill-switch — overrides [kill_switch] entirely when set.
[profiles.work.kill_switch]
enabled = true
allow_lan = false
ipv6 = true
dns_servers = ["1.1.1.1"]

[profiles.lab]
server = "lab-vpn.company.com"
name = "Lab VPN"
browser = "headless"      # different IdP — no Qt browser, just headless

[profiles.lab.credentials]
username = "admin"
totp_source = "none"     # don't prompt for TOTP
```

Resolution order for any setting: **CLI flag > per-profile field >
top-level config**.

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

## Profile groups

Bundle profiles together so a single command brings up several VPNs
at once (or stops all of them):

```bash
openconnect-saml groups add work vpn-eu vpn-us
openconnect-saml groups list
openconnect-saml groups connect work       # all members start in --detach mode
openconnect-saml groups disconnect work    # stops every group member
openconnect-saml groups remove work
```

Or in `config.toml`:

```toml
[profile_groups]
work = ["vpn-eu", "vpn-us"]
home = ["vpn-home"]
```

`groups connect` runs each member through the regular ``connect``
flow (with `--detach`), so per-profile settings, kill-switch, hooks,
and history all behave the same way.

## Importing AnyConnect XML profiles

Cisco's AnyConnect ships per-tenant `.xml` profile files at
`/opt/cisco/anyconnect/profile/*.xml`. To bulk-import them as
openconnect-saml profiles:

```bash
openconnect-saml profiles import-xml /opt/cisco/anyconnect/profile/MyVpn.xml
openconnect-saml profiles import-xml MyVpn.xml --prefix cisco-
openconnect-saml profiles import-xml MyVpn.xml --force   # overwrite existing
```

Each `<HostEntry>` block becomes one saved profile keyed by
`HostName` (with spaces converted to underscores). `--prefix STR`
namespaces the imports — useful when bulk-importing several files
that may share host names.

## Schema migrations

When the project's config schema gains optional fields or deprecates
old ones, ``profiles migrate`` applies the transformations
idempotently:

```bash
openconnect-saml profiles migrate           # dry-run, lists what would change
openconnect-saml profiles migrate --apply   # persist
```

Current migrations:

- Lift legacy `[default_profile]` into `[profiles.default]` so every
  install is multi-profile-aware.
- Drop `[2fauth]` / `[bitwarden]` / `[1password]` / `[pass]` sections
  that no profile references anymore.

`migrate` is safe to run on every config; if nothing applies it just
reports "No migrations needed".

## Active profile

`active_profile` in the config file marks the most recently connected
profile (set automatically on successful connect). It's used by the
`status` command to label live connections.
