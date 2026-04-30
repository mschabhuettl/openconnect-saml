"""Tests for the `groups` subcommand."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from openconnect_saml import config
from openconnect_saml.cli import _handle_groups_command


def _mk_cfg_with_profiles(*names):
    cfg = config.Config()
    for n in names:
        cfg.add_profile(n, {"server": f"{n}.example.com"})
    return cfg


def _args(action, **kw):
    base = {"groups_action": action}
    base.update(kw)
    return SimpleNamespace(**base)


class TestGroupsAdd:
    def test_add_group(self, capsys):
        cfg = _mk_cfg_with_profiles("eu", "us")
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.config.save"),
        ):
            rc = _handle_groups_command(_args("add", group_name="work", members=["eu", "us"]))
        assert rc == 0
        assert cfg.profile_groups["work"] == ["eu", "us"]

    def test_add_rejects_unknown_profiles(self, capsys):
        cfg = _mk_cfg_with_profiles("eu")
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(_args("add", group_name="work", members=["eu", "ghost"]))
        assert rc == 1
        # Group should not have been created
        assert "work" not in cfg.profile_groups


class TestGroupsList:
    def test_empty(self, capsys):
        cfg = config.Config()
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(_args("list"))
        assert rc == 0
        assert "No profile groups" in capsys.readouterr().out

    def test_lists_groups(self, capsys):
        cfg = _mk_cfg_with_profiles("eu", "us")
        cfg.profile_groups = {"work": ["eu", "us"], "home": ["eu"]}
        with patch("openconnect_saml.config.load", return_value=cfg):
            _handle_groups_command(_args("list"))
        out = capsys.readouterr().out
        assert "work" in out
        assert "home" in out
        assert "eu, us" in out


class TestGroupsRemove:
    def test_removes_group(self, capsys):
        cfg = _mk_cfg_with_profiles("eu")
        cfg.profile_groups = {"work": ["eu"]}
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.config.save"),
        ):
            rc = _handle_groups_command(_args("remove", group_name="work"))
        assert rc == 0
        assert "work" not in cfg.profile_groups

    def test_remove_unknown(self, capsys):
        cfg = config.Config()
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(_args("remove", group_name="nope"))
        assert rc == 1


class TestGroupsRename:
    def test_rename(self):
        cfg = _mk_cfg_with_profiles("eu")
        cfg.profile_groups = {"work": ["eu"]}
        with (
            patch("openconnect_saml.config.load", return_value=cfg),
            patch("openconnect_saml.config.save"),
        ):
            rc = _handle_groups_command(_args("rename", old_name="work", new_name="office"))
        assert rc == 0
        assert "office" in cfg.profile_groups
        assert "work" not in cfg.profile_groups

    def test_rename_unknown(self, capsys):
        cfg = config.Config()
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(_args("rename", old_name="ghost", new_name="x"))
        assert rc == 1

    def test_rename_target_exists(self, capsys):
        cfg = _mk_cfg_with_profiles("eu")
        cfg.profile_groups = {"a": ["eu"], "b": ["eu"]}
        with patch("openconnect_saml.config.load", return_value=cfg):
            rc = _handle_groups_command(_args("rename", old_name="a", new_name="b"))
        assert rc == 1


class TestProfileGroupsField:
    def test_empty_default(self):
        cfg = config.Config()
        assert cfg.profile_groups == {}

    def test_round_trip(self):
        cfg = config.Config(profile_groups={"work": ["eu", "us"]})
        assert cfg.profile_groups == {"work": ["eu", "us"]}
        d = cfg.as_dict()
        assert d["profile_groups"] == {"work": ["eu", "us"]}
