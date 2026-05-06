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

## FIDO2 hardware security keys

Hardware-key support for WebAuthn challenges (Yubikey, Nitrokey,
SoloKey, etc.):

- **Headless mode** uses the `python-fido2` library directly via USB
  HID. Install with `pip install "openconnect-saml[fido2]"`.
- **Chrome browser** uses Chromium's built-in WebAuthn — works out of
  the box. **This is the recommended path for hardware-key MFA.**
- **Qt browser** wires `webAuthUxRequested` (Qt-WebEngine ≥ 6.7), but
  see the warning below for a known limitation on PyPI installations.

A WebAuthn challenge during SAML auth surfaces as either a terminal
prompt (`Touch your security key…`) or a Qt / Chrome dialog depending
on the backend.

> **⚠️ `--browser qt` cannot drive hardware keys on PyPI installations.**
> The PyPI [`PyQt6-WebEngine`](https://pypi.org/project/PyQt6-WebEngine/)
> wheel ships Chromium with `WebUSB` compiled out of the build entirely
> (`disable-features=...,WebUSB`). Without that transport, Chromium
> can't enumerate USB security keys, so `navigator.credentials.get()`
> for FIDO2 is silently rejected at the C++ layer and Qt's
> `webAuthUxRequested` signal never fires — the Yubikey / Nitrokey
> LED never blinks. Documented in #24. There's no runtime workaround
> (`--enable-features=WebUSB` doesn't re-enable a feature stripped at
> build time); the fix would require a Qt rebuild with WebUSB linked
> in, which is out of scope for a Python wrapper. **Use `--browser
> chrome` for hardware-key MFA**, or wire your own browser via
> `--auth-script`. Distro Qt packages (e.g. Arch's
> `python-pyqt6-webengine`) may or may not work depending on how Qt
> was compiled there.

### Saving the ~150 MB Chromium download

`--browser chrome` defaults to a Playwright-bundled Chromium installed
via `playwright install chromium`. If you already have Chrome / Edge
installed system-wide, point Playwright at it with `--chrome-channel`:

```sh
openconnect-saml connect <profile> --browser chrome --chrome-channel chrome
```

Valid channels: `chrome`, `chrome-beta`, `chrome-dev`, `chrome-canary`,
`msedge`, `msedge-beta`, `msedge-dev`, `msedge-canary`. Skips the
Playwright-bundled Chromium download entirely.

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

## External authentication script (`--auth-script`)

When the built-in auto-flow can't drive your IdP — typically tenants
with bespoke MFA flows, ADFS / WS-Trust federation, or in-house SSO
gateways — you can hand off the SAML phase to your own script.

```bash
openconnect-saml connect work --auth-script /usr/local/bin/my-saml.sh
# or persistently:
openconnect-saml profiles set work auth_script /usr/local/bin/my-saml.sh
```

**Contract.** The wrapper runs your script as:

```
<script> <login_url> <token_cookie_name> <username>
```

with the password fed to **stdin** (one line, no trailing newline
added). Your script must print **the SSO token** to **stdout** and
exit 0; anything on stderr is captured for logging only. A non-zero
exit, an empty stdout, or exceeding the wrapper's `--timeout`
(default 30s) all fall back to the localhost callback server.

**Environment is restricted** to `PATH` and `HOME` only — the script
does not inherit `REQUESTS_CA_BUNDLE`, AWS credentials, keyring
tokens, or anything else from the wrapper's environment. Set what
you need explicitly inside the script.

**Security.** When `auth_script` is read from a profile config (rather
than passed on the CLI) the wrapper logs a `WARNING` at startup.
Anyone with write access to your config file could otherwise plant a
script that runs under `sudo` during connect — the warning gives you
a chance to notice. CLI-supplied paths skip the warning since they're
an explicit one-shot opt-in.
