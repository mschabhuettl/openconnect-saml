# Operations

Day-to-day running of the VPN: keeping it alive, running it as a system
service, getting notified about events, watching status, and reading
the audit log.

## Multiple simultaneous VPNs

Connect several gateways at once and manage them by profile name:

```bash
# Start each one in detached mode (returns once openconnect is running)
openconnect-saml connect work --detach
openconnect-saml connect lab  --detach

# See all live sessions
openconnect-saml sessions list

# Stop one
openconnect-saml disconnect lab

# Stop everything
openconnect-saml disconnect --all
```

Session state lives under
`$XDG_STATE_HOME/openconnect-saml/sessions/<profile>.json` (mode
`0600`). The files only carry metadata — profile name, server,
username, openconnect pid, start timestamp — never any secrets.

`status` automatically picks up recorded sessions, so the TUI / GUI
both surface the same view regardless of whether you're attached to
the connect process or not.

> **Note**: `--detach` works best when sudo is already cached or set
> to `NOPASSWD` for `openconnect`. Otherwise the password prompt
> appears after the supervisor has already exited.

## Auto-reconnect

```bash
# Unlimited retries with exponential backoff (30s, 60s, 120s, 300s)
openconnect-saml --server vpn.example.com --headless --reconnect

# Cap retries
openconnect-saml --server vpn.example.com --headless --reconnect --max-retries 5
```

Backoff resets on a successful re-authentication. Each retry emits a
`reconnecting` entry to the connection history with the attempt number
and delay.

## Systemd service

Persistent system-managed VPN:

```bash
# Install + enable
sudo openconnect-saml service install \
  --server vpn.example.com --user user@domain.com

# Manage
sudo openconnect-saml service start    --server vpn.example.com
sudo openconnect-saml service stop     --server vpn.example.com
openconnect-saml      service status
openconnect-saml      service logs     --server vpn.example.com -f

# Remove
sudo openconnect-saml service uninstall --server vpn.example.com
```

The unit lives at `/etc/systemd/system/openconnect-saml@<server>.service`
and runs in headless mode with `--reconnect`. Credentials still come
from the keyring — the service does not store secrets in the unit file.

## Notifications

Desktop notifications for connect / disconnect / reconnect / error
events:

```bash
openconnect-saml connect work --notify
```

Or globally in `config.toml`:

```toml
notifications = true
```

Backends: Linux (`notify-send`), macOS (`osascript`), generic
(terminal bell as fallback).

## Live status

```bash
openconnect-saml status                  # one-shot
openconnect-saml status --watch          # refreshes every 2s
openconnect-saml status --json           # machine-readable
openconnect-saml status --watch --json   # JSON stream
```

The TUI shows: profile, server, user, uptime, IP address, TX / RX
bytes, reconnect count. Install `pip install "openconnect-saml[tui]"`
for the rich-formatted table; without it the output falls back to plain
text.

JSON output is one self-contained object per print:

```json
{
  "connected": true,
  "pid": 12345,
  "server": "vpn.example.com",
  "interface": "tun0",
  "ip": "10.0.0.42",
  "uptime": "1h 23m",
  "tx": 12345678,
  "rx": 87654321,
  "profile": "work",
  "user": "user@example.com",
  "reconnects": 0
}
```

If no VPN is up, the object is `{"connected": false}`.

## Connection history

Every connect / disconnect / reconnect / error event is logged to
`$XDG_STATE_HOME/openconnect-saml/history.jsonl` (owner-read 0o600,
rotated at 512 KiB). One JSON object per line.

```bash
openconnect-saml history show           # human-readable, newest first
openconnect-saml history show -n 20     # last 20
openconnect-saml history show --json
openconnect-saml history stats          # aggregated summary
openconnect-saml history stats --json
openconnect-saml history clear
openconnect-saml history path
```

`history stats` aggregates: total connections, total time online, mean
session length, error count, profile usage breakdown, last-connect
timestamp.

**Privacy / security**

- Only metadata: timestamp, event, server URL, profile, username,
  duration, free-text message.
- Never logs passwords, TOTP codes, session cookies.
- Enabled by default. Disable per-session with `--no-history`, globally
  with `connection_history = false` in config.

## Interactive TUI

Full-screen, keyboard-driven terminal UI:

```bash
openconnect-saml tui
```

Layout: profile list on the left, live status / history on the right.
Keys:

| Key | Action |
|---|---|
| `↑/k` / `↓/j` | Move profile selection |
| `Enter` / `c` | Connect to selected profile |
| `d` | Disconnect |
| `r` | Refresh profile list |
| `s` | Show live status pane |
| `h` | Show history pane |
| `q` / `Esc` | Quit (active VPN keeps running) |

Requires the `[tui]` extra (`rich`). For monitoring-only use the
non-interactive `status` command instead.

## Tk GUI

```bash
openconnect-saml gui
```

Three tabs: *Profiles* (list, add / edit / delete dialogs, connect /
disconnect, log pane), *Status* (live counters / rate, refreshed every
2s), *History* (recent events, refreshed every 5s). The toolbar has a
global Browser-backend dropdown (`chrome` / `qt` / `headless`). Tk-only
— no extra dependencies.

## On-connect / on-disconnect hooks

Run a command when the VPN connects or disconnects:

```bash
openconnect-saml connect work \
  --on-connect "/usr/local/bin/route-add" \
  --on-disconnect "/usr/local/bin/route-cleanup"
```

The connect hook has a 30s timeout; disconnect 5s. Standard env vars
inherit, plus `VPN_INTERFACE` and `VPN_SERVER` are set by openconnect
itself.
