"""Tests for the encrypted profile-backup module."""

from __future__ import annotations

import json

import pytest

from openconnect_saml import encrypted_backup as eb

SAMPLE_PAYLOAD = {
    "version": 1,
    "profiles": {
        "work": {"server": "vpn.example.com", "user_group": "engineers"},
        "lab": {"server": "lab.example.com"},
    },
}


class TestRoundTrip:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = json.dumps(SAMPLE_PAYLOAD).encode("utf-8")
        token = eb.encrypt(plaintext, "correct horse battery staple")
        out = eb.decrypt(token, "correct horse battery staple")
        assert json.loads(out) == SAMPLE_PAYLOAD

    def test_decrypt_wrong_passphrase(self):
        token = eb.encrypt(b"hello", "right")
        with pytest.raises(ValueError, match="Wrong passphrase"):
            eb.decrypt(token, "wrong")

    def test_decrypt_corrupted_file(self):
        with pytest.raises(ValueError):
            eb.decrypt(b"this is not a backup file", "any")

    def test_decrypt_unknown_version(self):
        bad = b"OPENCONNECT_SAML_BACKUP\nv99\nAAAA\nXXXX\n"
        with pytest.raises(ValueError, match="format version"):
            eb.decrypt(bad, "any")

    def test_each_encrypt_uses_fresh_salt(self):
        # Two encrypts of the same plaintext should differ (random salt)
        a = eb.encrypt(b"hello", "pw")
        b = eb.encrypt(b"hello", "pw")
        assert a != b

    def test_format_layout(self):
        token = eb.encrypt(b"hello", "pw")
        text = token.decode("utf-8").strip()
        lines = text.split("\n")
        assert lines[0] == eb.MAGIC
        assert lines[1] == eb.FORMAT_VERSION
        assert len(lines) == 4


class TestExportImport:
    def test_export_to_file(self, tmp_path):
        out = tmp_path / "backup.enc"
        rc = eb.export_encrypted(SAMPLE_PAYLOAD, out, passphrase="hunter2")
        assert rc == 0
        assert out.exists()
        # Decrypt and verify
        loaded = eb.import_encrypted(out, passphrase="hunter2")
        assert loaded == SAMPLE_PAYLOAD

    def test_import_wrong_passphrase(self, tmp_path):
        out = tmp_path / "backup.enc"
        eb.export_encrypted(SAMPLE_PAYLOAD, out, passphrase="hunter2")
        with pytest.raises(ValueError):
            eb.import_encrypted(out, passphrase="wrong")
