# Networking

## Split-tunnel routing

Route only specific subnets through the VPN, or exclude specific
ranges from the tunnel:

```bash
# Include only these
openconnect-saml connect work --route 10.0.0.0/8 --route 172.16.0.0/12

# Exclude (bypass VPN for these)
openconnect-saml connect work --no-route 192.168.0.0/16

# Combine
openconnect-saml connect work --route 10.0.0.0/8 --no-route 10.0.99.0/24
```

Or per-profile in `config.toml`:

```toml
[profiles.work]
server = "vpn.company.com"
routes = ["10.0.0.0/8", "172.16.0.0/12"]
no_routes = ["192.168.0.0/16"]
```

CIDR validity is checked by `openconnect-saml config validate`.

## Kill-switch

Blocks every outbound connection except to the VPN server, loopback,
and tunnel interfaces. Two backends share the same CLI surface
(`killswitch enable / disable / status`):

- **Linux (iptables)** — production-quality. Creates an
  `OPENCONNECT_SAML_KILLSWITCH` chain jumped to from `OUTPUT`,
  optional ip6tables mirror, conntrack-based reply allowance.
- **macOS (pf)** — *experimental* in v0.9.0. Loads a self-contained
  pf anchor (`openconnect-saml-killswitch`) via `pfctl -a`. Doesn't
  touch `/etc/pf.conf`; rules disappear cleanly on disable. macOS
  users should test thoroughly before relying on it for sensitive
  traffic.

DNS resolvers and RFC1918 LAN ranges can be allow-listed individually
on both backends.

### One-shot — auto-clears on disconnect

```bash
openconnect-saml connect work --kill-switch \
  --ks-allow-dns 1.1.1.1 --ks-allow-dns 9.9.9.9 \
  --ks-allow-lan
```

### Standalone — persists until disabled

```bash
sudo openconnect-saml killswitch enable -s vpn.example.com \
  --ks-allow-dns 1.1.1.1
sudo openconnect-saml killswitch status
sudo openconnect-saml killswitch disable
```

Persistent configuration:

```toml
[kill_switch]
enabled = true
allow_lan = false
ipv6 = true
dns_servers = ["1.1.1.1", "9.9.9.9"]
```

### Flags

| Flag | Effect |
|---|---|
| `--kill-switch` | Enable for the session |
| `--ks-allow-dns IP` | Allow DNS to this resolver (repeatable) |
| `--ks-allow-lan` | Allow RFC1918 LAN traffic |
| `--ks-no-ipv6` | Skip ip6tables rules |
| `--ks-port PORT` | VPN server port to allow (default 443) |
| `--ks-sudo TOOL` | Override privilege-escalation tool (default: autodetect) |

### Safety

- Linux + macOS only; other platforms surface
  `KillSwitchNotSupported` immediately.
- **Linux**: only chain `OPENCONNECT_SAML_KILLSWITCH` is installed;
  removal is idempotent via `killswitch disable`. If the CLI crashes
  and the chain is stuck:

  ```bash
  sudo iptables -F  OPENCONNECT_SAML_KILLSWITCH
  sudo iptables -X  OPENCONNECT_SAML_KILLSWITCH
  sudo ip6tables -F OPENCONNECT_SAML_KILLSWITCH
  sudo ip6tables -X OPENCONNECT_SAML_KILLSWITCH
  ```

- **macOS**: only the `openconnect-saml-killswitch` pf anchor is
  populated; flushing it (`sudo pfctl -a openconnect-saml-killswitch -F all`)
  removes our rules without affecting the rest of pf. Anchor entry
  goes away on reboot.

- Session-based `--kill-switch` tears down on disconnect. The persistent
  form (configured in `[kill_switch]` or via `killswitch enable`) stays
  up until explicitly disabled.

## Proxy

```bash
openconnect-saml --server vpn.example.com --proxy http://proxy.local:8080
openconnect-saml --server vpn.example.com --proxy socks5://proxy.local:1080
```

## SSL / TLS legacy compatibility

Some older Cisco appliances need legacy SSL renegotiation:

```bash
openconnect-saml --server vpn.example.com --ssl-legacy
```

This sets `OP_LEGACY_SERVER_CONNECT` on the SSL context (Python ≥ 3.12).

## Self-signed certificates: `--no-cert-check`

Internal corporate gateways often use a private CA or self-signed
certificate that's not in the system trust store. Use
`--no-cert-check` to bypass TLS verification on the SAML auth
phase *and* tell openconnect itself to skip the system trust store:

```bash
openconnect-saml --server vpn.internal.example.com --no-cert-check
```

What it does:

- Sets `session.verify = False` and `session.trust_env = False` on
  the requests session — this is **important** because
  `REQUESTS_CA_BUNDLE` / `SSL_CERT_FILE` env vars (set by default on
  most Linux distros) would otherwise silently re-enable verification.
- Adds `--no-system-trust` to the openconnect command line.
- Keeps `--servercert <hash>` pinning intact — the leaf certificate's
  hash from the SAML auth response is still enforced. This binds the
  trust to the actual cert, not the trust chain.

> ⚠️ Only use this on networks you trust. For public-internet VPNs
> always rely on a properly trusted certificate.

## Headless redirect-host whitelist: `--allowed-hosts`

When using `--headless` mode for unattended authentication, the
`requests` session follows up to 20 redirects. To prevent a
compromised gateway from POSTing credentials to an attacker-controlled
host, you can pin the allowed hostnames:

```bash
openconnect-saml --headless \
  --server vpn.example.com \
  --allowed-hosts 'login.microsoftonline.com,*.duosecurity.com'
```

Rules:

- Comma-separated list. Whitespace is trimmed.
- Exact hostname match: `idp.example.com` matches only that.
- Glob with `*.suffix` matches any subdomain: `*.duosecurity.com`
  matches `api-1a.duosecurity.com` but **not** `duosecurity.com` itself.
- The gateway and the gateway-supplied login URL hosts are
  auto-allowed (the gateway is authoritative for those redirects).
- A redirect off the whitelist raises `HeadlessAuthError` and exits
  fail-closed.

Default (flag unset): no host enforcement, behaviour identical to
v0.20.0 and earlier.
