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
