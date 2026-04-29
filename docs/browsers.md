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

Visible Chromium window, native WebAuthn, recommended for unusual MFA
flows where Qt struggles:

```bash
openconnect-saml --server vpn.example.com --browser chrome
openconnect-saml connect work --browser chrome
openconnect-saml --server vpn.example.com --browser chrome --browser-display-mode hidden
```

Requires `pip install "openconnect-saml[chrome]"` and one-time
`playwright install chromium`.

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
