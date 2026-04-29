"""Tests for the ``profiles migrate`` subcommand."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from openconnect_saml import config, profiles


class TestMigrateDryRun:
    def test_no_changes_when_already_clean(self, capsys):
        cfg = config.Config()
        cfg.add_profile("work", {"server": "vpn.example.com"})
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._migrate_profiles(SimpleNamespace(apply=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert "No migrations needed" in out

    def test_legacy_default_profile_detected(self, capsys):
        # Old-style config with only [default_profile] and no [profiles]
        cfg = config.Config(default_profile={"address": "vpn", "user_group": "", "name": "Default"})
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._migrate_profiles(SimpleNamespace(apply=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert "applicable" in out.lower()
        assert "Dry-run only" in out

    def test_unused_provider_section_detected(self, capsys):
        # A 2fauth section but no profile uses it
        cfg = config.Config(twofauth=config.TwoFAuthConfig(url="x", token="y", account_id=1))
        cfg.add_profile("work", {"server": "vpn"})
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._migrate_profiles(SimpleNamespace(apply=False))
        assert rc == 0
        out = capsys.readouterr().out
        assert "Drop unused" in out


class TestMigrateApply:
    def test_legacy_default_profile_migrated(self):
        cfg = config.Config(
            default_profile={"address": "vpn.example.com", "user_group": "", "name": "Old"}
        )
        saved = []
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save", side_effect=saved.append),
        ):
            rc = profiles._migrate_profiles(SimpleNamespace(apply=True))
        assert rc == 0
        assert "default" in cfg.profiles
        assert cfg.profiles["default"].server == "vpn.example.com"
        assert cfg.active_profile == "default"
        assert saved, "Config should have been persisted"

    def test_unused_2fauth_section_dropped(self):
        cfg = config.Config(twofauth=config.TwoFAuthConfig(url="x", token="y", account_id=1))
        cfg.add_profile("work", {"server": "vpn"})
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._migrate_profiles(SimpleNamespace(apply=True))
        assert cfg.twofauth is None

    def test_used_2fauth_section_kept(self):
        cfg = config.Config(twofauth=config.TwoFAuthConfig(url="x", token="y", account_id=1))
        cfg.add_profile(
            "work",
            {
                "server": "vpn",
                "credentials": {"username": "u", "totp_source": "2fauth"},
            },
        )
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):
            profiles._migrate_profiles(SimpleNamespace(apply=True))
        assert cfg.twofauth is not None
