"""Tests for the config subcommand (show/validate/path/edit)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openconnect_saml import config_cmd


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    cfg_dir = tmp_path / "openconnect-saml"
    cfg_dir.mkdir()
    yield cfg_dir


def write_config(cfg_dir: Path, content: str) -> Path:
    p = cfg_dir / "config.toml"
    p.write_text(content)
    p.chmod(0o600)
    return p


class TestRedact:
    def test_redacts_password(self):
        data = {"password": "secret123", "username": "alice"}
        out = config_cmd._redact(data)
        assert out["password"] == "***"
        assert out["username"] == "alice"

    def test_redacts_token(self):
        data = {"token": "abc", "url": "https://x"}
        out = config_cmd._redact(data)
        assert out["token"] == "***"
        assert out["url"] == "https://x"

    def test_empty_value_not_redacted(self):
        data = {"password": "", "token": None}
        out = config_cmd._redact(data)
        # Empty / None — leave as-is (don't write "***")
        assert out["password"] == ""
        assert out["token"] is None

    def test_nested(self):
        data = {"profiles": {"work": {"credentials": {"password": "s", "username": "a"}}}}
        out = config_cmd._redact(data)
        assert out["profiles"]["work"]["credentials"]["password"] == "***"
        assert out["profiles"]["work"]["credentials"]["username"] == "a"

    def test_list_in_structure(self):
        data = {"servers": [{"token": "x"}, {"token": "y"}]}
        out = config_cmd._redact(data)
        assert out["servers"][0]["token"] == "***"
        assert out["servers"][1]["token"] == "***"


class TestValidate:
    def test_missing_file(self, tmp_path):
        path = tmp_path / "nope.toml"
        issues = config_cmd.validate_config(path)
        assert any(s == "error" and "not found" in m for s, m in issues)

    def test_valid_config(self, tmp_config_dir):
        p = write_config(tmp_config_dir, """
[profiles.work]
server = "vpn.example.com"
user_group = "engineering"
""")
        issues = config_cmd.validate_config(p)
        assert not any(s == "error" for s, _ in issues)

    def test_invalid_toml(self, tmp_config_dir):
        p = write_config(tmp_config_dir, "this is = not valid = toml")
        issues = config_cmd.validate_config(p)
        assert any(s == "error" and "toml" in m.lower() for s, m in issues)

    def test_profile_missing_server(self, tmp_config_dir):
        p = write_config(tmp_config_dir, """
[profiles.work]
user_group = "engineering"
""")
        issues = config_cmd.validate_config(p)
        assert any(s == "error" and "server" in m for s, m in issues)

    def test_active_profile_missing(self, tmp_config_dir):
        p = write_config(tmp_config_dir, """
active_profile = "nope"
[profiles.work]
server = "vpn.example.com"
""")
        issues = config_cmd.validate_config(p)
        assert any(s == "warning" and "active_profile" in m for s, m in issues)

    def test_2fauth_reference_without_section(self, tmp_config_dir):
        p = write_config(tmp_config_dir, """
[profiles.work]
server = "vpn.example.com"

[profiles.work.credentials]
username = "alice"
totp_source = "2fauth"
""")
        issues = config_cmd.validate_config(p)
        assert any(s == "warning" and "2fauth" in m for s, m in issues)

    def test_overly_permissive_mode(self, tmp_config_dir):
        import os
        p = write_config(tmp_config_dir, """
[profiles.work]
server = "vpn.example.com"
""")
        # Make it world-readable
        os.chmod(p, 0o644)
        issues = config_cmd.validate_config(p)
        if os.name == "posix":
            assert any(s == "warning" and "permissive" in m.lower() for s, m in issues)


class TestCmdPath:
    def test_path_prints(self, tmp_config_dir, capsys):
        rc = config_cmd._cmd_path()
        assert rc == 0
        captured = capsys.readouterr()
        assert "config.toml" in captured.out


class TestCmdShow:
    def test_show_missing_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        rc = config_cmd._cmd_show(as_json=False)
        assert rc == 1

    def test_show_redacts_secrets(self, tmp_config_dir, capsys):
        write_config(tmp_config_dir, """
[2fauth]
url = "https://2fa.example.com"
token = "supersecret"
account_id = 1

[profiles.work]
server = "vpn.example.com"
""")
        rc = config_cmd._cmd_show(as_json=False)
        assert rc == 0
        captured = capsys.readouterr()
        assert "supersecret" not in captured.out
        assert "***" in captured.out

    def test_show_json(self, tmp_config_dir, capsys):
        write_config(tmp_config_dir, """
[2fauth]
token = "s"
url = "https://x"
account_id = 1

[profiles.work]
server = "vpn.example.com"
""")
        rc = config_cmd._cmd_show(as_json=True)
        assert rc == 0
        captured = capsys.readouterr()
        # Parse JSON (ignoring the trailing comment line)
        lines = captured.out.splitlines()
        json_text = "\n".join(line for line in lines if not line.startswith("#"))
        parsed = json.loads(json_text)
        assert parsed["2fauth"]["token"] == "***"


class TestCmdValidate:
    def test_valid(self, tmp_config_dir, capsys):
        write_config(tmp_config_dir, """
[profiles.work]
server = "vpn.example.com"
""")
        rc = config_cmd._cmd_validate()
        assert rc == 0

    def test_invalid_returns_1(self, tmp_config_dir, capsys):
        write_config(tmp_config_dir, """
[profiles.work]
user_group = "engineering"
""")
        rc = config_cmd._cmd_validate()
        assert rc == 1


class TestHandler:
    def test_unknown_action(self, capsys):
        class Args:
            config_action = "mystery"

        rc = config_cmd.handle_config_command(Args())
        assert rc == 1
