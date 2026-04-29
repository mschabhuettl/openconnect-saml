# Configuration

`openconnect-saml` keeps state in a single TOML file. Default location:

- Linux: `~/.config/openconnect-saml/config.toml`
- macOS: `~/Library/Application Support/openconnect-saml/config.toml`
  (XDG-compatible if `XDG_CONFIG_HOME` is set)
- Windows: `%APPDATA%\openconnect-saml\config.toml`

The file is created automatically with mode `0600` on first save.

## Setup wizard

Easiest way to create the first profile:

```bash
openconnect-saml setup
```

Asks for: server URL, username, TOTP source (`local` / `2fauth` /
`bitwarden` / `1password` / `pass` / `none`), provider details if
applicable, browser backend, auto-reconnect, notifications, profile
name. Saves a profile and optionally sets it as the default.

## TOML structure

```toml
# Default profile picked when no name / --profile is given
[default_profile]
server = "vpn.example.com"
user_group = ""
name = "My VPN"

[credentials]
username = "user@example.com"
totp_source = "local"        # local | 2fauth | bitwarden | 1password | pass | none

# Named profiles (zero or more)
[profiles.work]
server = "vpn.company.com"
user_group = "employees"
name = "Work VPN"
routes = ["10.0.0.0/8"]
no_routes = ["192.168.0.0/16"]

[profiles.work.credentials]
username = "user@company.com"
totp_source = "1password"

# Provider sections (optional, only when used)
[2fauth]
url = "https://2fauth.example.com"
token = "eyJ0eXAiOiJKV1QiLC..."
account_id = 42

[bitwarden]
item_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

[1password]
item = "vpn-work-mfa"
vault = "Engineering"

[pass]
entry = "vpn/work-totp"

[kill_switch]
enabled = false
allow_lan = false
ipv6 = true
dns_servers = ["1.1.1.1", "9.9.9.9"]

# Behaviour flags
notifications = false
connection_history = true
on_connect = ""
on_disconnect = ""
timeout = 30
window_width = 800
window_height = 600

# Marks the most recently connected profile (set automatically)
active_profile = "work"
```

See [authentication.md](authentication.md) for full TOTP-provider
config details and [networking.md](networking.md) for kill-switch
options.

## Auto-fill rules

Custom HTML-element fill rules for unusual IdP login pages:

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

Default rules cover Azure AD, Microsoft Account, and most Cisco IdPs.

## `config` subcommand

Inspect, validate, and edit the active config:

```bash
openconnect-saml config path                # print resolved file path
openconnect-saml config show                # TOML, secrets redacted
openconnect-saml config show --json
openconnect-saml config validate            # schema + semantic checks
openconnect-saml config edit                # opens $EDITOR
```

`validate` catches:

- TOML syntax errors
- Missing `server` on a profile
- Unresolvable `active_profile`
- Missing `[2fauth]` / `[bitwarden]` / `[1password]` / `[pass]`
  sections referenced by a profile's `totp_source`
- Invalid CIDRs in `routes` / `no_routes`
- Overly-permissive file modes (anything other than `0600`)

## Overriding the config path

```bash
# CLI flag (per-invocation)
openconnect-saml --config /etc/openconnect-saml/work.toml status

# Environment variable (persistent in a shell)
export OPENCONNECT_SAML_CONFIG=/etc/openconnect-saml/work.toml
openconnect-saml status
```

Useful for multi-tenant setups, testing, and CI. The override applies
to every subcommand and the legacy CLI form.
