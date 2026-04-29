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
