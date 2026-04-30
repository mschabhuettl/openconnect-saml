"""Encrypted profile backup / restore.

Wraps the existing JSON profile-export with an authenticated, password-derived
symmetric encryption layer so a backup can be safely committed to a private
git repo or stored on a USB stick. Uses Fernet (AES-128-CBC + HMAC-SHA256)
with PBKDF2-HMAC-SHA256 (480 000 iterations, 16-byte random salt).

File layout (UTF-8 lines):

    OPENCONNECT_SAML_BACKUP\\nv1\\n<base64 salt>\\n<base64 token>\\n

The salt + iteration count are encoded in the file so the decoder doesn't
need any out-of-band metadata. The passphrase is taken from stdin or a
prompt — it is never persisted anywhere.

Why Fernet vs. age/openssl: Fernet ships with the ``cryptography`` package
which is already a transitive dependency via ``keyring`` →
``secretstorage`` on Linux, so we don't grow the dependency surface.
"""

from __future__ import annotations

import base64
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

MAGIC = "OPENCONNECT_SAML_BACKUP"
FORMAT_VERSION = "v1"
PBKDF2_ITERATIONS = 480_000
SALT_BYTES = 16


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte key with PBKDF2-HMAC-SHA256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def encrypt(plaintext: bytes, passphrase: str) -> bytes:
    """Encrypt ``plaintext`` with ``passphrase`` and return the file bytes."""
    from cryptography.fernet import Fernet

    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive_key(passphrase, salt)
    token = Fernet(key).encrypt(plaintext)
    body = f"{MAGIC}\n{FORMAT_VERSION}\n{base64.b64encode(salt).decode()}\n{token.decode()}\n"
    return body.encode("utf-8")


def decrypt(file_bytes: bytes, passphrase: str) -> bytes:
    """Decrypt a backup file produced by :func:`encrypt`."""
    from cryptography.fernet import Fernet, InvalidToken

    text = file_bytes.decode("utf-8", errors="strict")
    parts = text.strip().split("\n")
    if len(parts) != 4:
        raise ValueError("Malformed backup file (expected 4 header lines)")
    magic, version, salt_b64, token = parts
    if magic != MAGIC:
        raise ValueError(f"Not an openconnect-saml backup (got magic={magic!r})")
    if version != FORMAT_VERSION:
        raise ValueError(f"Unsupported backup format version: {version}")
    salt = base64.b64decode(salt_b64)
    key = _derive_key(passphrase, salt)
    try:
        return Fernet(key).decrypt(token.encode("utf-8"))
    except InvalidToken as exc:
        raise ValueError("Wrong passphrase or backup file is corrupted") from exc


def _prompt_passphrase(confirm: bool = False) -> str:
    """Read a passphrase from the controlling terminal."""
    pw = getpass.getpass("Backup passphrase: ")
    if not pw:
        print("Error: passphrase cannot be empty.", file=sys.stderr)
        sys.exit(1)
    if confirm:
        again = getpass.getpass("Confirm passphrase: ")
        if again != pw:
            print("Error: passphrases do not match.", file=sys.stderr)
            sys.exit(1)
    return pw


def export_encrypted(payload: dict, target: Path | None, passphrase: str | None = None) -> int:
    """Write an encrypted JSON-payload backup. ``target=None`` writes to stdout.

    The payload is the same dict ``profiles export`` produces (already with
    secrets stripped). Encrypting it adds a second authentication factor
    so users can also commit the file to a private repo without leaking
    metadata like server URLs and usernames.
    """
    if passphrase is None:
        passphrase = _prompt_passphrase(confirm=True)
    data = encrypt(json.dumps(payload, indent=2, default=str).encode("utf-8"), passphrase)

    if target is None or str(target) == "-":
        os.write(1, data)
        return 0

    target_path = Path(target)
    try:
        target_path.write_bytes(data)
        with _suppress_chmod_error():
            target_path.chmod(0o600)
    except OSError as exc:
        print(f"Error writing {target_path}: {exc}", file=sys.stderr)
        return 1
    print(f"✓ Encrypted backup written to {target_path}")
    return 0


def import_encrypted(source: Path, passphrase: str | None = None) -> dict:
    """Decrypt a backup file and return the embedded JSON payload."""
    if passphrase is None:
        passphrase = _prompt_passphrase(confirm=False)
    raw = decrypt(Path(source).read_bytes(), passphrase)
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _suppress_chmod_error():
    import contextlib

    return contextlib.suppress(OSError, NotImplementedError)
