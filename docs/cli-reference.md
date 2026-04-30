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
| `profiles` | List / add / remove / rename / show / export / import named profiles |
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
--config FILE              Override XDG config path (or set $OPENCONNECT_SAML_CONFIG)
-l, --log-level LEVEL      ERROR / WARNING / INFO / DEBUG (default: INFO)
```

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
--timeout SECONDS          HTTP timeout (default: 30)
--ac-version STRING        AnyConnect Version (default: 4.7.00136)
--no-history               Don't log this session to history.jsonl
--authenticate FORMAT      Auth only, output cookie (json | shell)
--detach                   Background the openconnect process; stop with
                           'openconnect-saml disconnect [PROFILE]'
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
openconnect-saml profiles add NAME --server HOST [--user U] [--user-group G] [--display-name N] [--totp-source S]
openconnect-saml profiles remove NAME
openconnect-saml profiles rename OLD NEW
openconnect-saml profiles show NAME [--json]
openconnect-saml profiles export [NAME] [--file FILE] [--format json|nmconnection]
openconnect-saml profiles import FILE|- [--as NAME] [--force]
openconnect-saml profiles migrate [--apply]
```

## `history` subcommand

```bash
openconnect-saml history show [--limit N] [--json]
openconnect-saml history stats [--json]
openconnect-saml history clear
openconnect-saml history path
```

## `service` subcommand (Linux / systemd)

```bash
sudo openconnect-saml service install -s HOST -u USER [--browser B] [--max-retries N]
sudo openconnect-saml service uninstall -s HOST
sudo openconnect-saml service start -s HOST
sudo openconnect-saml service stop -s HOST
openconnect-saml      service status [-s HOST]
openconnect-saml      service logs   [-s HOST] [-f]
```

## `config` subcommand

```bash
openconnect-saml config path
openconnect-saml config show [--json]
openconnect-saml config validate
openconnect-saml config edit
```

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
