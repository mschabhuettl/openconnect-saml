# Diagnostics & troubleshooting

## `doctor` command

```bash
openconnect-saml doctor                          # local checks only
openconnect-saml doctor --server vpn.example.com # also probe DNS / TCP / HTTPS
```

Exit codes:

- `0` — every check passed
- `1` — at least one check failed
- `2` — at least one check warned (non-fatal)

### Checks performed

| # | Check | Why |
|---|---|---|
| 1 | Platform | sanity context for the rest of the report |
| 2 | Python ≥ 3.10 | minimum supported runtime |
| 3 | `openconnect` binary | required to bring up the tunnel |
| 4 | sudo / doas | needed to configure the tunnel device |
| 5 | `/dev/net/tun` (Linux) | required device for the VPN tunnel |
| 6 | Core Python deps | `attrs`, `keyring`, `lxml`, `pyotp`, `requests`, `structlog`, `toml` |
| 7 | Optional Python deps | `[gui]`, `[chrome]`, `[fido2]`, `[tui]` extras |
| 8 | Keyring backend | secure storage for passwords / TOTP secrets |
| 9 | Config dir + permissions | `0600` mode on `config.toml` |
| 10 | Environment hygiene | warns if `BW_SESSION` / `OP_SESSION_*` / similar are set |
| 11 | DNS resolution (`--server`) | catches typos / split-DNS issues |
| 12 | TCP reachability (`--server`) | firewall / routing |
| 13 | SAML endpoint probe (`--server`) | HTTPS GET to the gateway, expects 200/302/303/307 or AnyConnect headers |
| 14 | Kill-switch state (Linux) | warns if a leftover chain is blocking traffic |

The HTTPS probe is new in v0.8.4. It catches misconfigured URLs (404 to
the wrong path), TLS errors, and corporate proxies that intercept the
gateway.

## Common problems

### "AuthenticationError: SAML auth-request is missing sso-v2-login"

The server doesn't speak SAML on this URL. Run
`openconnect-saml doctor --server <url>` — the SAML endpoint check
should flag what's wrong. Try alternate paths like
`https://vpn.example.com/group_name`.

### Hardware token doesn't blink with `--browser qt`

Requires QtWebEngine ≥ 6.7. Earlier versions silently drop WebAuthn
challenges. Either upgrade or fall back to `--browser chrome`.

### "Cannot retrieve saved password from keyring"

No keyring backend is available. On Linux: install `gnome-keyring` or
`kwallet` (and a session bus). On servers / CI: pass credentials via
flags, or use a TOTP provider that doesn't depend on the keyring
(`2fauth`, `1password`, `pass`).

### "openconnect: Failed to bind local tun device"

`/dev/net/tun` missing or unreadable. In containers:

```bash
docker run --cap-add=NET_ADMIN --device=/dev/net/tun ...
```

On bare metal: `sudo modprobe tun`.

### Reconnect loop never recovers

Ctrl-C the loop, run `openconnect-saml history show -n 20` to see what
events fired, and `--log-level DEBUG` for verbose output. If
`--browser chrome` works but `--browser qt` doesn't, file an issue with
both transcripts.

### Kill-switch chain stuck after crash

```bash
sudo iptables  -F  OPENCONNECT_SAML_KILLSWITCH
sudo iptables  -X  OPENCONNECT_SAML_KILLSWITCH
sudo ip6tables -F  OPENCONNECT_SAML_KILLSWITCH
sudo ip6tables -X  OPENCONNECT_SAML_KILLSWITCH
```

Or run `sudo openconnect-saml killswitch disable`, which is idempotent.

### Setup wizard runs but profile isn't recognized

`config validate` will tell you why — most often a missing required
field on a profile or a referenced provider section that doesn't
exist.

## Exit codes (reference)

| Code | Meaning |
|-----:|---|
|   0  | Success |
|   1  | Generic failure |
|   2  | Platform not supported / browser terminated |
|   3  | Authentication response missing expected fields |
|   4  | HTTP error during authentication |
|  17  | No AnyConnect profile found |
|  18  | No AnyConnect profile selected |
|  19  | Invalid arguments |
|  20  | No superuser tool / not running as Administrator |
|  21  | 2FAuth TOTP config missing |
|  22  | Bitwarden TOTP config missing |
|  23  | 1Password TOTP config missing |
|  24  | pass TOTP config missing |
|  130 | Interrupted (Ctrl-C) |

## Reporting bugs

Please include:

1. Output of `openconnect-saml doctor --server <vpn-url>`.
2. The CLI command you ran, with `--log-level DEBUG`.
3. Last 30 lines of `history show -n 30`.
4. Anonymised version of your `config show` (it auto-redacts secrets).

Issue tracker: <https://github.com/mschabhuettl/openconnect-saml/issues>
