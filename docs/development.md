# Development

## Setup

```bash
git clone https://github.com/mschabhuettl/openconnect-saml
cd openconnect-saml

# Install uv (https://docs.astral.sh/uv) — the project standardises on it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies (runtime + dev)
make dev          # = uv sync --dev
```

To work on browser / hardware-token / TUI features, also install the
relevant extras:

```bash
uv sync --extra dev --extra fido2 --extra tui --extra chrome
playwright install chromium      # one-time, for the chrome backend
```

## Make targets

| Target | What it runs |
|---|---|
| `make dev` | `uv sync --dev` |
| `make test` | `uv run pytest -v` |
| `make lint` | `uv run ruff check .` + `ruff format --check .` |
| `make format` | `ruff check --fix . && ruff format .` |
| `make clean` | Remove `dist/`, caches, `__pycache__` |

## Running tests

```bash
make test                                      # full suite
uv run pytest tests/test_profiles.py -v        # one file
uv run pytest -k nmconnection                  # filter
uv run pytest --cov=openconnect_saml           # with coverage
```

CI runs on Ubuntu (Python 3.10–3.13) and Windows (3.12). Coverage
gate: ≥ 50 % (`pyproject.toml` → `[tool.coverage.report]`).

## Project layout

```
openconnect_saml/
├── cli.py                # argparse + dispatch
├── app.py                # main run-loop, reconnect, kill-switch wiring
├── authenticator.py      # SAML XML protocol with the VPN gateway
├── saml_authenticator.py # SAML browser flow (Qt)
├── browser/              # Qt + Playwright/Chromium browser backends
│   ├── browser.py
│   ├── chrome.py
│   └── webengine_process.py
├── headless.py           # Headless auto-form-fill auth
├── fido2_auth.py         # FIDO2 USB-HID for headless mode
├── totp_providers.py     # local / 2fauth / bitwarden / 1password / pass
├── config.py             # TOML config + Credentials + keyring
├── config_cmd.py         # `config` subcommand
├── profiles.py           # `profiles` subcommand (incl. nmconnection export)
├── setup_wizard.py       # `setup` interactive wizard
├── service.py            # systemd unit management
├── history.py            # JSONL audit log
├── killswitch.py         # iptables rules
├── doctor.py             # `doctor` subcommand
├── tui.py                # `status` command (rich + plain)
├── gui.py                # `gui` command (Tk launcher)
├── notify.py             # Desktop notifications
├── completion.py         # Shell completions
└── xml_utils.py          # Shared XXE-safe XML parser

tests/                    # pytest, mirrors the module layout
.github/workflows/        # CI, integration-test, security, publish, AUR, release
aur/                      # AUR PKGBUILD + .SRCINFO
docs/                     # Reference documentation (this directory)
```

## Release flow

1. Bump `version` in `pyproject.toml`.
2. Update `CHANGELOG.md` with a new section.
3. Commit on `release/vX.Y.Z`, fast-forward `main`.
4. Push the tag (`git push origin vX.Y.Z`) — that triggers:
   - `release.yml` → builds wheels + creates the GitHub Release
   - `publish.yml` → uploads to PyPI
   - `aur-publish.yml` → updates the AUR package

The PyPI environment requires `id-token: write` (already configured for
trusted publishing). The AUR job uses `webfactory/ssh-agent` with the
`AUR_SSH_KEY` secret.

## Coding conventions

- Ruff handles formatting and linting (`pyproject.toml` →
  `[tool.ruff]`). Line length 100, ignore `E501`.
- Default to **no comments**. Add one only when the *why* is non-obvious.
- Tests live next to the module they cover (`tests/test_<module>.py`).
- New CLI flags should be tested in `tests/test_cli_args.py`.
- Keep changes focused. A bug fix should not also rename three
  variables; a refactor should not also add a feature.

## Filing issues / PRs

- Bugs: include `doctor --server <url>`, the failing command with
  `--log-level DEBUG`, the relevant CHANGELOG version, and your OS.
- PRs: keep them focused on one concern; add tests for new
  behaviour; update the CHANGELOG under an `## [Unreleased]` heading.

Issue tracker:
<https://github.com/mschabhuettl/openconnect-saml/issues>
