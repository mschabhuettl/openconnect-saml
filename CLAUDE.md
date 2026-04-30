# Notes for Claude (and other agents) working on this repo

## Release policy

**Never push a tag (= release) until the CI matrix on the target commit is
green on every OS.** This is enforced in CI now (`release.yml` and
`publish.yml` re-run the full test matrix from `test.yml` via
`workflow_call` and gate the build/publish/AUR jobs on it), but the same
rule applies before tagging:

1. Push the change to a branch.
2. Wait for the **CI** workflow to finish on that branch — *all* matrix
   jobs must be green, including `windows-latest, 3.12`.
3. Only then merge to `main`, tag, and push the tag.

The Windows job has historically been the one that fails when local
Linux pytest is green (different process model, no openconnect binary,
POSIX modules like `termios`/`tty` only appear when actually loaded).
Treat a failing Windows job exactly the same as a failing Linux job —
do not ship.

## Local pre-flight (Linux dev box)

Before pushing anything that ends up tagged:

```sh
.venv/bin/pytest -q --no-header
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

These cover Linux + lint. Windows is covered by GitHub Actions only;
trust the matrix.

## Release flow (manual)

Once CI is green on `main`:

```sh
git checkout main
git pull
git tag -a vX.Y.Z -m "..."
git push origin main          # not strictly needed if already pushed
git push origin vX.Y.Z        # this triggers release / publish / AUR
```

The tag push fires `release.yml` and `publish.yml`. Both re-run the test
matrix as a `tests` gate job; build/publish/AUR only run if the gate is
green. So a Windows-only failure on the tagged commit will hold the
release back even if the developer forgot to check.

## Things that have bitten Windows in the past

- POSIX-only stdlib modules (`termios`, `tty`, `fcntl`, `pwd`, `grp`,
  `pty`) — keep them either lazy-imported or inside `if sys.platform != "win32"`.
- `pgrep`, `ip`, `iptables`, `pfctl` — these binaries don't exist on
  Windows; callers must catch `FileNotFoundError` and degrade.
- `/proc`, `/etc/`, `/var/run/` paths — wrap in `Path(...).exists()`
  or `try: ... except OSError`.
- Signals: `signal.SIGUSR1`, `signal.SIGKILL` — not on Windows. Use
  `signal.SIGTERM` and `process.terminate()`.
- File mode bits and `os.chmod(..., 0o600)` — Windows ignores these,
  so any test that asserts on them needs `@pytest.mark.skipif(...)`.
