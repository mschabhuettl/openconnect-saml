"""Tests for `profiles set` and `profiles copy`."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from openconnect_saml import config, profiles


def _args(profile_name, field, value):
    return SimpleNamespace(profile_name=profile_name, field=field, value=value)


def _cfg_with_profile():
    cfg = config.Config()
    cfg.add_profile(
        "work",
        {
            "server": "vpn.example.com",
            "user_group": "engineers",
            "credentials": {"username": "alice@example.com", "totp_source": "local"},
        },
    )
    return cfg


class TestSetFieldString:
    def test_set_server(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            rc = profiles._set_profile_field(_args("work", "server", "new.example.com"))
        assert rc == 0
        assert cfg.get_profile("work").server == "new.example.com"

    def test_set_browser(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "browser", "chrome"))
        assert cfg.get_profile("work").browser == "chrome"

    def test_clear_browser_with_empty_string(self):
        cfg = _cfg_with_profile()
        cfg.get_profile("work").browser = "qt"
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "browser", ""))
        assert cfg.get_profile("work").browser is None


class TestSetFieldBool:
    def test_set_notify_true(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "notify", "true"))
        assert cfg.get_profile("work").notify is True

    def test_set_notify_no(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "notify", "no"))
        assert cfg.get_profile("work").notify is False

    def test_clear_notify(self):
        cfg = _cfg_with_profile()
        cfg.get_profile("work").notify = True
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "notify", ""))
        assert cfg.get_profile("work").notify is None

    def test_invalid_bool_rejected(self, capsys):
        cfg = _cfg_with_profile()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._set_profile_field(_args("work", "notify", "maybe"))
        assert rc == 1
        assert "boolean" in capsys.readouterr().err


class TestSetCredentialsField:
    def test_set_username(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "username", "bob@example.com"))
        assert cfg.get_profile("work").credentials.username == "bob@example.com"

    def test_set_totp_source(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._set_profile_field(_args("work", "totp_source", "1password"))
        assert cfg.get_profile("work").credentials.totp_source == "1password"


class TestCopyProfile:
    def test_copy_creates_independent_profile(self):
        cfg = _cfg_with_profile()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            args = SimpleNamespace(source="work", dest="work-copy", force=False)
            rc = profiles._copy_profile(args)
        assert rc == 0
        assert "work-copy" in cfg.profiles
        # Mutating the copy doesn't affect the source
        cfg.profiles["work-copy"].server = "different.example.com"
        assert cfg.profiles["work"].server == "vpn.example.com"

    def test_copy_unknown_source(self, capsys):
        cfg = config.Config()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            args = SimpleNamespace(source="ghost", dest="x", force=False)
            rc = profiles._copy_profile(args)
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_copy_refuses_overwrite(self, capsys):
        cfg = _cfg_with_profile()
        cfg.add_profile("existing", {"server": "x"})
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            args = SimpleNamespace(source="work", dest="existing", force=False)
            rc = profiles._copy_profile(args)
        assert rc == 1

    def test_copy_force_overwrites(self):
        cfg = _cfg_with_profile()
        cfg.add_profile("existing", {"server": "old.example.com"})
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            args = SimpleNamespace(source="work", dest="existing", force=True)
            rc = profiles._copy_profile(args)
        assert rc == 0
        assert cfg.profiles["existing"].server == "vpn.example.com"


class TestErrors:
    def test_unknown_profile(self, capsys):
        cfg = config.Config()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._set_profile_field(_args("ghost", "server", "x"))
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_unknown_field(self, capsys):
        cfg = _cfg_with_profile()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._set_profile_field(_args("work", "garbage", "x"))
        assert rc == 1
        assert "unsupported field" in capsys.readouterr().err
