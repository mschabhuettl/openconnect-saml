# Migrating

## From `openconnect-sso`

`openconnect-saml` is a maintained fork of [`vlaci/openconnect-sso`](https://github.com/vlaci/openconnect-sso),
combining features from [`kowyo/openconnect-lite`](https://github.com/kowyo/openconnect-lite)
and additional MFA / observability / packaging work.

### One-shot migration

```bash
pip uninstall openconnect-sso
pip install "openconnect-saml[gui]"   # or your preferred extras

# Reuse your existing config — no rename required, but if you want a
# clean slate use the new XDG path:
mv ~/.config/openconnect-sso ~/.config/openconnect-saml

# Same CLI surface
openconnect-saml --server vpn.example.com
```

### What's different

| Area | `openconnect-sso` | `openconnect-saml` |
|---|---|---|
| CLI entry point | `openconnect-sso` | `openconnect-saml` (single binary, both legacy and subcommand-based usage) |
| Config dir | `~/.config/openconnect-sso/` | `~/.config/openconnect-saml/` (override with `--config FILE` or `$OPENCONNECT_SAML_CONFIG`) |
| Browser backend | Qt only | `qt`, `chrome`, `headless` |
| MFA | Qt browser + manual | Qt + Chrome + native FIDO2 + 2FAuth + Bitwarden + 1Password + pass |
| Profile management | None | `profiles add/remove/list/show/rename/export/import` |
| NetworkManager export | No | `profiles export --format nmconnection` |
| Kill-switch | No | iptables-based, session or persistent |
| Reconnect | No | `--reconnect [--max-retries N]` with backoff |
| Connection history | No | JSONL audit log + `history stats` |
| Diagnostics | No | `doctor` subcommand with HTTPS probe |
| systemd integration | No | `service install/start/stop/status/logs` |
| Status TUI | No | `status [--watch] [--json]` |

### Config-file compatibility

The TOML schema is a strict superset of `openconnect-sso`'s — your
existing config file works unchanged. New optional sections:

- `[profiles.<name>]` — multi-profile support
- `[2fauth]`, `[bitwarden]`, `[1password]`, `[pass]` — TOTP providers
- `[kill_switch]` — persistent kill-switch
- `connection_history`, `notifications`, top-level scalars

Run `openconnect-saml config validate` after the migration to verify
the schema.

### Env vars

`openconnect-saml` honors `OPENCONNECT_SAML_CONFIG` for config-path
override (new in v0.8.4) — the old project had no such mechanism.

## From `openconnect-lite`

`openconnect-saml` includes the modernization work from `openconnect-lite`
(notably the maintained dependencies and Python 3.10+ baseline) plus
the larger feature surface from `openconnect-sso`. If you were on
`openconnect-lite`:

```bash
pip uninstall openconnect-lite
pip install openconnect-saml
```

Config path was `~/.config/openconnect-sso/` for `lite` too — same
notes apply.

## From a vendor's Cisco Secure Client / AnyConnect

The wrapper drives `openconnect`, which speaks the Cisco AnyConnect
protocol. Install both:

```bash
sudo apt install openconnect       # or your distro equivalent
pip install "openconnect-saml[gui]"
```

Then run the [setup wizard](configuration.md#setup-wizard) and point
it at your gateway. SAML/SSO authentication is automatic; the password
is stored in the system keyring; TOTP comes from the provider you
configured. Hardware tokens (Yubikey / Nitrokey) work in all three
browser backends.
