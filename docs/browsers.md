# Browser backends

`openconnect-saml` drives the SAML/SSO flow in one of three browser
backends. Pick the one that matches your setup with `--browser`:

| Backend | Flag | Best for |
|---|---|---|
| **Headless** | `--headless` *or* `--browser headless` | Servers, containers, CI |
| **Qt6 WebEngine** | `--browser qt` *(default with `[gui]`)* | Desktop, full IdP UI |
| **Chrome / Chromium** | `--browser chrome` | Hardware tokens, Duo, Azure number-matching |

## Headless

No display required. Two-stage authentication:

1. **Auto** — HTTP + form-parser submits credentials directly.
2. **Fallback** — if auto fails (CAPTCHA, unusual MFA), the CLI prints
   a URL and starts a local callback server. Open the URL in any
   browser on any device, complete login, and the callback finishes
   the flow.

```bash
# Auto-authenticate with saved credentials
openconnect-saml --server vpn.example.com --headless --user user@example.com

# Auth-only mode — emit cookie, don't connect
openconnect-saml --server vpn.example.com --headless --authenticate json
openconnect-saml --server vpn.example.com --headless --authenticate shell
```

## Qt6 WebEngine

The default when the `[gui]` extra is installed. Fully-featured
embedded browser with WebAuthn / FIDO2 support since v0.8.2 (requires
QtWebEngine ≥ 6.7).

```bash
openconnect-saml --server vpn.example.com               # legacy invocation
openconnect-saml connect work --browser qt              # explicit
```

The Qt browser handles `webAuthUxRequested` so YubiKey / Nitrokey LEDs
light up on Duo / Cisco prompts.

## Chrome / Chromium (Playwright)

Visible Chromium window, native WebAuthn (FIDO2 hardware keys work
out of the box), recommended for unusual MFA flows where Qt struggles
or for FIDO2-only tenants:

```bash
openconnect-saml --server vpn.example.com --browser chrome
openconnect-saml connect work --browser chrome
openconnect-saml --server vpn.example.com --browser chrome --browser-display-mode hidden
```

Requires `pip install "openconnect-saml[chrome]"` (or AUR
`python-playwright` — **not** `aur/playwright`, which is the
Node.js library) and a one-time `playwright install chromium` to
download the ~150 MB Chromium bundle.

Chrome launches with its sandbox enabled.

### Skipping the Playwright Chromium download

If you already have Chrome / Edge installed system-wide, point
Playwright at it via `--chrome-channel`:

```bash
openconnect-saml connect work --browser chrome --chrome-channel chrome
# or msedge / chrome-beta / chrome-dev / chrome-canary / msedge-beta / …
```

Valid channels: `chrome`, `chrome-beta`, `chrome-dev`, `chrome-canary`,
`msedge`, `msedge-beta`, `msedge-dev`, `msedge-canary`. Plain
`chromium` is **not** a Playwright channel — Arch's stock
`pacman -S chromium` users either install AUR `google-chrome`
(then `--chrome-channel chrome`), or just run
`playwright install chromium` once (it caches under
`~/.cache/ms-playwright/` and never re-downloads). Full caveat in
[authentication.md](authentication.md#saving-the-150-mb-chromium-download).

## Minimal profile GUI

For a Cisco-Secure-Client-style launcher around saved profiles:

```bash
openconnect-saml gui
```

A small Tk window listing profiles, a Browser dropdown
(chrome / qt / headless — picks per-launch), Connect / Disconnect /
Refresh buttons, and a live process log. Intentionally minimal —
advanced flags still go through the CLI.

## Display modes for Qt

Useful for debugging or running under Wayland without window decorations:

```bash
--browser-display-mode shown    # default
--browser-display-mode hidden   # platform=minimal Qt plugin (off-screen)
```

## Window size for Qt

```bash
--window-size 1024x768
```

Or persistently in `config.toml`:

```toml
window_width = 1024
window_height = 768
```

## VPN cookie cache

VPN cookie caching and session reuse apply to the existing AnyConnect SAML flow.
This wrapper does not implement authentication for other OpenConnect VPN
protocols. Passing `--protocol` to OpenConnect does not change the wrapper's
authentication flow.

VPN cookies are cached by default in the OS keyring, separately for each
gateway, login group, username, and profile. The cookie, final gateway URL,
and certificate fingerprint are saved together. Cookies never go into
`config.toml`; if no keyring is available, login continues without caching.

On the next foreground connection, or detached connection on macOS/Linux,
the saved cookie is sent to OpenConnect
before opening a browser or prompting for credentials. If the gateway rejects
it, the entry is removed and browser SSO is attempted once. Network and local
setup errors do not trigger a login. `--reconnect` also uses this behavior.

- `--forget-token`: delete the entry for this account/gateway and log in again.
- `--no-token-cache`: skip cache reads and writes for this invocation.
- `token_cache = false` in top-level config: disable caching persistently.

`--forget-token` does not clear your browser's other cookies, saved preferences,
or extensions. Existing browser SSO state may still complete a fresh VPN login.

Auth-only (`--authenticate`), detached connections on Windows, and kill-switch
connections use fresh authentication. Kill-switch authentication finishes
before enabling the firewall, which would otherwise block SSO refresh.

On macOS/Linux, connections with caching enabled keep the server
session when you press Ctrl-C or run `disconnect PROFILE`. The tunnel stops
and its routing script restores the network; the next connection tries the
saved cookie. Use `disconnect PROFILE --logout` to log the session out instead.
Shutdown has a timeout, with forced logout as a fallback if cleanup stalls.

Server expiration and revocation still apply. Connections with caching disabled
retain normal logout behavior.
`--detach` leaves the tunnel running after the launcher exits. See
[OpenConnect's signal documentation](https://www.infradead.org/openconnect/manual.html).

On Windows, session preservation after Ctrl-C or `disconnect` is not implemented.
Foreground connections can try a cached cookie when a keyring is available,
but reuse after disconnect is not guaranteed. Detached connections use fresh
authentication and return without confirming tunnel startup. Live Windows VPN
authentication, cached-cookie refresh, username-only login, and persistent Chrome
profiles have not been manually verified.

## Persistent Chrome profiles

Use a dedicated profile to retain browser cookies, settings, and extensions:

```bash
openconnect-saml --server vpn.example.com --browser chrome \
  --chrome-channel chrome \
  --chrome-user-data-dir "$HOME/.local/share/openconnect-saml/work-chrome" \
  --user user@example.com --username-only
```

`--username-only` fills the username and leaves password entry, MFA, and form
submission to you and the browser. `--user` alone still prompts for a missing
VPN password in the terminal. Save these options in
[config](configuration.md#saved-username-and-chrome-settings) to avoid repeating them.

Closing the login window after SSO completes still uses the completed login.
Closing it before a completion cookie is available exits without connecting.
After SSO, sudo may ask for your computer's account password to create the
tunnel. This local authorization is separate from VPN login and token reuse.

Use a separate directory from your everyday Chrome profile. Playwright does
not support automating Chrome's default profile, and two running browser
instances cannot share one user-data directory. Close the dedicated browser
before connecting again.

To install extensions, open the same dedicated profile manually first:

```bash
open -na "Google Chrome" --args \
  --user-data-dir="$HOME/.local/share/openconnect-saml/work-chrome"
```

Install the extension, complete its authorization, then quit Chrome before
connecting. Subsequent login windows reuse that profile and allow installed
extensions. Apple's iCloud Passwords extension still needs user authorization;
its full login flow has not been verified by this project. Chrome may also
request macOS Keychain access. See
[Apple's extension setup](https://support.apple.com/guide/passwords/get-extensions-mchlf7ac261e/mac)
and [Playwright persistent contexts](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context).
