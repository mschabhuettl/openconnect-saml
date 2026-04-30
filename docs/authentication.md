# Authentication

`openconnect-saml` supports several credential / second-factor flows.

## Username + password

The username comes from `--user`, the saved profile, or the
`[credentials]` config section. The password is requested interactively
on first connect and stored in the system keyring afterward (Linux:
Secret Service / GNOME Keyring / KWallet, macOS: Keychain, Windows:
Credential Manager).

```bash
openconnect-saml --server vpn.example.com --user alice@example.com
# → prompted for password once, then cached
```

To clear cached credentials:

```bash
openconnect-saml --user alice@example.com --reset-credentials
```

## TOTP providers

Supported providers (selected via `--totp-source` or the
`totp_source` profile field):

| Provider | Setup |
|---|---|
| `local` *(default)* | Secret stored in the system keyring; prompted on first use |
| `2fauth` | Self-hosted [2FAuth](https://docs.2fauth.app/) instance |
| `bitwarden` | Bitwarden vault item via the `bw` CLI |
| `1password` | 1Password item via the `op` CLI |
| `pass` | `pass-otp` extension on top of [`pass`](https://www.passwordstore.org) |
| `none` | Skip the TOTP prompt entirely |

### `local`

The default. On first connect you're asked for the TOTP secret
(base32 string from the QR/setup screen). It's saved to the keyring
under `totp/<username>` and used automatically thereafter.

To suppress the prompt for accounts that don't use TOTP:

```bash
openconnect-saml --server vpn.example.com --no-totp
# or persistently:
openconnect-saml profiles add work --server vpn.example.com --totp-source none
```

### 2FAuth

```bash
openconnect-saml --server vpn.example.com --headless \
  --totp-source 2fauth \
  --2fauth-url https://2fauth.example.com \
  --2fauth-token YOUR_PERSONAL_ACCESS_TOKEN \
  --2fauth-account-id 42
```

Or in `config.toml`:

```toml
[2fauth]
url = "https://2fauth.example.com"
token = "eyJ0eXAiOiJKV1QiLC..."
account_id = 42

[credentials]
username = "user@example.com"
totp_source = "2fauth"
```

**Setup**

1. Install [2FAuth](https://docs.2fauth.app/) and add your VPN TOTP
   account.
2. Create a Personal Access Token (Settings → OAuth → Personal Access
   Tokens).
3. Note the account ID (URL when editing the account, or via the API).

> ⚠️ Use HTTPS. HTTP endpoints will trigger a warning.

### Bitwarden

```bash
openconnect-saml --server vpn.example.com --headless \
  --totp-source bitwarden \
  --bw-item-id YOUR_VAULT_ITEM_UUID
```

```toml
[bitwarden]
item_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

[credentials]
username = "user@example.com"
totp_source = "bitwarden"
```

**Setup**

1. Install the [Bitwarden CLI](https://bitwarden.com/help/cli/) (`bw`).
2. `bw login` and `bw unlock` → export `BW_SESSION`.
3. `bw list items --search "VPN"` → note the `id` field.

### 1Password

Delegates to the `op` CLI. Sign in once (biometric / system
integration / `op signin`):

```bash
openconnect-saml connect work \
  --totp-source 1password \
  --1password-item "vpn-work-mfa" \
  --1password-vault "Engineering"
```

```toml
[1password]
item = "vpn-work-mfa"           # UUID, name, or share URL
vault = "Engineering"           # optional
account = "acme.1password.com"  # optional, multi-account

[profiles.work.credentials]
totp_source = "1password"
```

### pass (`pass-otp`)

Uses the [`pass-otp`](https://github.com/tadfisher/pass-otp) extension.
The password entry must contain an `otpauth://` or `totp://` URI.

```bash
openconnect-saml connect work \
  --totp-source pass \
  --pass-entry "vpn/work-totp"
```

```toml
[pass]
entry = "vpn/work-totp"

[profiles.work.credentials]
totp_source = "pass"
```

Requires: `pass`, `pass-otp`, an unlocked GPG agent.

## FIDO2 / hardware security keys

Hardware-key support for WebAuthn challenges (Yubikey, Nitrokey,
SoloKey, etc.):

- **Headless mode** uses the `python-fido2` library directly via USB
  HID. Install with `pip install "openconnect-saml[fido2]"`.
- **Qt browser** wires `webAuthUxRequested` (Qt-WebEngine ≥ 6.7) so the
  key LEDs light up natively.
- **Chrome browser** uses Chromium's built-in WebAuthn — works out of
  the box.

A WebAuthn challenge during SAML auth surfaces as either a terminal
prompt (`Touch your security key…`) or a Qt / Chrome dialog depending
on the backend.

## Skipping prompts

| Goal | Flag |
|---|---|
| Don't ask for TOTP | `--no-totp` *or* `--totp-source none` |
| Don't ask for password | Pre-populate the keyring or set `password` in the env-bound credential helper |
| Reset everything | `--reset-credentials` |
| Auth-only run (print cookie, exit) | `--auth-only` (alias for `--authenticate shell`) |

`--auth-only` is the most common use of `--authenticate` — it auths
the user, prints the cookie + cert hash on stdout, and exits without
spawning openconnect. Useful for CI / scripts:

```bash
eval "$(openconnect-saml --server vpn.example.com --user me --auth-only)"
echo "$COOKIE"
```

For the JSON variant, use the original `--authenticate json` form.

## Client certificates

For VPNs that require a client certificate in addition to (or instead
of) SAML authentication:

```bash
openconnect-saml --server vpn.example.com \
  --cert ~/certs/work.pem \
  --cert-key ~/certs/work.key
```

Both paths support `~` tilde expansion. Internally the values are
forwarded to openconnect as `--certificate` / `--sslkey`.

Per-profile equivalent:

```toml
[profiles.work]
server = "vpn.company.com"
cert = "~/certs/work.pem"
cert_key = "~/certs/work.key"
```

Resolution order: CLI flag > per-profile field. If you have multiple
VPNs each with its own client cert, the per-profile fields are the
clean way to manage that.
