# CLI reference

Every flag and subcommand. For the conceptual guide see the topic
docs ([browsers](browsers.md), [authentication](authentication.md),
[profiles](profiles.md), [networking](networking.md),
[operations](operations.md)).

## Subcommands

| Subcommand | Purpose |
|---|---|
| `connect [PROFILE]` | Authenticate + launch openconnect (or use a saved profile) |
| `disconnect [PROFILE]` | Stop a running VPN session by profile name |
| `sessions` | List active VPN sessions |
| `groups` | Manage groups of profiles (multi-VPN connect/disconnect) |
| `run PROFILE -- CMD` | Connect, run a command, disconnect (transient session) |
| `profiles` | List / add / copy / remove / rename / show / set / export / import / import-xml / migrate named profiles |
| `setup` | Interactive configuration wizard |
| `gui` | Tk launcher with Profiles / Status / History tabs |
| `tui` | Full-screen interactive terminal UI (rich) |
| `status [--watch] [--json]` | Show live VPN connection state |
| `history` | Inspect / clear / aggregate the connection audit log |
| `service` | Install / start / stop / status / logs for a systemd unit |
| `config` | path / show / validate / edit the config file |
| `doctor` | One-shot system diagnostics |
| `killswitch` | enable / disable / status the iptables kill-switch |
| `completion` | Emit shell-completion scripts (bash / zsh / fish) |

The legacy form `openconnect-saml --server …` (no subcommand) is still
supported.

## Global flags

```
-V, --version              Show version and exit
--check                    With --version: also fetch the latest release from PyPI
--config FILE              Override XDG config path (or set $OPENCONNECT_SAML_CONFIG)
-q, --quiet                Suppress informational output; only errors are printed
-l, --log-level LEVEL      ERROR / WARNING / INFO / DEBUG (default: INFO)
```

`--quiet` raises the threshold to `WARNING`; an explicit `--log-level
ERROR` still wins. `--config FILE` and `$OPENCONNECT_SAML_CONFIG`
both override the XDG default for one invocation.

## `connect` flags

### Server

```
-p, --profile PATH         Use a profile from this file or directory (legacy)
-P, --profile-selector     Always display profile selector
--proxy URL                Use a proxy server (http://, socks5://)
-s, --server HOST          VPN server to connect to
-g, --usergroup GROUP      Override usergroup
--authgroup GROUP          Required authentication login selection
```

### Browser / display

```
--headless                 No browser, terminal-only authentication
--browser BACKEND          qt | chrome | headless
--browser-display-mode M   shown | hidden
--window-size WxH          Browser window size (Qt only)
--useragent STRING         Custom user-agent for the SAML browser
```

### Credentials

```
-u, --user NAME            Authenticate as the given user
--reset-credentials        Delete saved credentials from keyring and exit
--auth-only                Friendly alias for --authenticate shell (auth, print cookie, exit)
--cert FILE                Client certificate (PEM) — passed to openconnect as --certificate
--cert-key FILE            Client certificate's private key (PEM) — passed as --sslkey
```

### TOTP providers

```
--totp-source SOURCE       local | 2fauth | bitwarden | 1password | pass | none
--no-totp                  Skip the TOTP prompt entirely (alias for --totp-source none)
--2fauth-url URL
--2fauth-token TOKEN
--2fauth-account-id ID
--bw-item-id UUID
--1password-item ITEM
--1password-vault VAULT
--1password-account ACCT
--pass-entry PATH
```

### Reconnect

```
--reconnect                Auto-reconnect when the VPN drops
--max-retries N            Cap reconnect attempts (default: unlimited)
```

### Routing

```
--route CIDR               Include subnet in tunnel (repeatable)
--no-route CIDR            Exclude subnet from tunnel (repeatable)
```

### Notifications / hooks

```
--notify                   Desktop notifications for VPN events
--on-connect CMD           Run a command after connect
--on-disconnect CMD        Run a command on disconnect
--on-error CMD             Run a command if auth/connect fails (sets $RC = exit code)
```

### Kill-switch

```
--kill-switch              Block non-VPN traffic for the session
--ks-allow-dns IP          Allow DNS resolver (repeatable)
--ks-allow-lan             Allow RFC1918 LAN traffic
--ks-no-ipv6               Skip ip6tables rules
--ks-port PORT             VPN server port to allow (default: 443)
--ks-sudo TOOL             Override privilege-escalation tool
```

### Connection options

```
--no-sudo                  Don't use sudo (e.g. with --script-tun)
--csd-wrapper PATH         CSD/hostscan wrapper script
--ssl-legacy               Enable legacy SSL renegotiation
--no-cert-check            Skip TLS certificate verification during the SAML auth
                           phase. Also passed through to openconnect itself.
                           Bypasses REQUESTS_CA_BUNDLE / SSL_CERT_FILE env vars.
--allowed-hosts H,H,...    Hostname whitelist for the headless redirect chain
                           (supports '*.example.com'). Gateway + login URL hosts
                           are auto-allowed; others are refused.
--timeout SECONDS          HTTP timeout (default: 30)
--ac-version STRING        AnyConnect Version (default: 4.7.00136)
--no-history               Don't log this session to history.jsonl
--authenticate FORMAT      Auth only, output cookie (json | shell)
--detach, --background     Run openconnect in the background; stop with
                           'openconnect-saml disconnect [PROFILE]'
--wait SECONDS             With --detach: block up to SECONDS until the tunnel
                           interface appears before returning (default: 0)
```

## `disconnect` subcommand

```bash
openconnect-saml disconnect [PROFILE]    # stop one session
openconnect-saml disconnect --all        # stop every active session
openconnect-saml disconnect              # equivalent to --all when no profile
```

## `sessions` subcommand

```bash
openconnect-saml sessions list [--json]
```

Shows profile, pid, server, and start timestamp for every active
session recorded under `$XDG_STATE_HOME/openconnect-saml/sessions/`.

### openconnect passthrough

Anything after `--` (or unknown options after the profile name) is
passed through to `openconnect`:

```bash
openconnect-saml --server vpn.example.com -- --script /etc/vpnc/vpnc-script
```

## `profiles` subcommand

```bash
openconnect-saml profiles list
openconnect-saml profiles add NAME --server HOST [--user U] [--user-group G] \
    [--display-name N] [--totp-source S] [--browser B] [--notify]
openconnect-saml profiles copy SRC DST [--force]
openconnect-saml profiles remove NAME
openconnect-saml profiles rename OLD NEW
openconnect-saml profiles show NAME [--json]
openconnect-saml profiles set NAME FIELD VALUE
openconnect-saml profiles export [NAME] [--file FILE] [--format json|nmconnection|encrypted]
openconnect-saml profiles import FILE|- [--as NAME] [--force]
openconnect-saml profiles import-xml FILE [--prefix STR] [--force]
openconnect-saml profiles migrate [--apply]
```

**`profiles set NAME FIELD VALUE`** — programmatic field editor. Allowed
fields: `server`, `user_group`, `name`, `browser`, `notify`, `on_connect`,
`on_disconnect`, `cert`, `cert_key`, `username`, `totp_source`. Booleans
accept `true|false|yes|no|1|0`. Empty string clears optional fields.

**`profiles copy SRC DST`** duplicates an existing profile. The copy is
independent of the source; mutating one doesn't affect the other.

## `history` subcommand

```bash
openconnect-saml history show [--limit N] [--json] \
    [--filter PROFILE] [--event EVENT] [--since WHEN]
openconnect-saml history stats [--json]
openconnect-saml history export [--format csv|json] [-o FILE]
openconnect-saml history clear
openconnect-saml history path
```

`--since` accepts an ISO 8601 timestamp or a relative phrase like
`"30 minutes ago"`, `"2 hours ago"`, `"1 day ago"`. `--event` takes
one of `connected | disconnected | reconnecting | error`.

`history export` writes the full log as either CSV (default) or JSON.
CSV columns: timestamp, event, profile, user, server, duration_seconds,
message — directly importable into spreadsheets / BI tools.

## `service` subcommand (Linux / systemd)

System-mode units (`/etc/systemd/system/`, requires sudo):

```bash
sudo openconnect-saml service install -s HOST -u USER [--browser B] [--max-retries N]
sudo openconnect-saml service uninstall -s HOST
sudo openconnect-saml service start -s HOST
sudo openconnect-saml service stop -s HOST
openconnect-saml      service status [-s HOST]
openconnect-saml      service logs   [-s HOST] [-f]
```

User-mode units (`~/.config/systemd/user/`, no sudo) — append `--user`
(or its alias `--user-unit`) to any of the above:

```bash
openconnect-saml service install --user -s HOST -u USER
openconnect-saml service start --user -s HOST
openconnect-saml service status --user
```

Tip: `loginctl enable-linger` keeps user services running across logouts.

The status / start / stop / uninstall / logs subcommands auto-detect
which mode (system vs. user) the unit is installed in, so `--user`
isn't strictly required after install.

## `groups` subcommand

```bash
openconnect-saml groups list
openconnect-saml groups add NAME PROFILE [PROFILE...]
openconnect-saml groups rename OLD NEW
openconnect-saml groups remove NAME
openconnect-saml groups connect NAME      # brings every member up via --detach
openconnect-saml groups disconnect NAME
```

## `disconnect` and `sessions` subcommands

```bash
openconnect-saml disconnect [PROFILE]    # stop one session
openconnect-saml disconnect --all        # stop every active session
openconnect-saml sessions list [--json]
```

## `run` subcommand

```bash
openconnect-saml run PROFILE [--wait SECONDS] -- COMMAND [ARGS...]
```

Brings up the profile in the background, waits up to `--wait`
seconds (default 15) for the tunnel, runs the command in the
foreground, and tears the tunnel down on exit (regardless of how
the command exited). Useful for one-shot scripts that need the VPN.

## `config` subcommand

```bash
openconnect-saml config path
openconnect-saml config show [--json]
openconnect-saml config validate
openconnect-saml config edit
openconnect-saml config diff OTHER.toml
openconnect-saml config import OTHER.toml [--force]
```

`config diff` produces a unified diff after redacting both sides; safe
to share for troubleshooting. `config import` deep-merges another TOML
into the active config (existing keys win unless `--force`).

## `setup` subcommand

```bash
openconnect-saml setup
openconnect-saml setup --advanced
```

The default wizard asks for server, username, TOTP, browser, reconnect,
notifications. `--advanced` adds prompts for client cert, on-connect /
on-disconnect hooks, and per-profile kill-switch.

## `doctor` subcommand

```bash
openconnect-saml doctor [-s HOST] [--json]
```

## `killswitch` subcommand (Linux)

```bash
sudo openconnect-saml killswitch enable -s HOST [--ks-allow-dns IP] [--ks-allow-lan] [--ks-no-ipv6] [--ks-port N] [--ks-sudo TOOL]
sudo openconnect-saml killswitch disable
openconnect-saml      killswitch status
```

## `completion` subcommand

```bash
openconnect-saml completion bash      # emit script to stdout
openconnect-saml completion zsh
openconnect-saml completion fish
openconnect-saml completion install   # auto-install to default location
```
