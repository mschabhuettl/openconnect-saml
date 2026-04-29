"""Tests for profile export/import."""

from __future__ import annotations

import json
from unittest.mock import patch

from openconnect_saml import config, profiles


def _mk_cfg(profs_data=None, **kwargs):
    """Build a Config with the given profiles."""
    cfg = config.Config(**kwargs)
    if profs_data:
        for name, data in profs_data.items():
            cfg.add_profile(name, data)
    return cfg


class TestExport:
    def test_export_single_to_stdout(self, capsys):
        cfg = _mk_cfg(
            {
                "work": {
                    "server": "vpn.example.com",
                    "user_group": "eng",
                    "name": "Work",
                }
            }
        )
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = "work"
                file = None

            profiles._export_profile(Args())
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["version"] == 1
        assert parsed["profile"]["server"] == "vpn.example.com"
        assert parsed["profile"]["_name"] == "work"

    def test_export_missing_profile(self, capsys):
        cfg = _mk_cfg()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = "nope"
                file = None

            rc = profiles._export_profile(Args())
        assert rc == 1

    def test_export_all(self, capsys):
        cfg = _mk_cfg(
            {
                "work": {"server": "vpn.example.com"},
                "home": {"server": "home.example.com"},
            }
        )
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = None
                file = None

            profiles._export_profile(Args())
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "profiles" in parsed
        assert "work" in parsed["profiles"]
        assert "home" in parsed["profiles"]

    def test_export_to_file(self, tmp_path):
        cfg = _mk_cfg({"work": {"server": "vpn.example.com"}})
        out = tmp_path / "out.json"
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = "work"
                file = str(out)

            profiles._export_profile(Args())
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["profile"]["server"] == "vpn.example.com"

    def test_export_strips_2fauth_token(self, capsys):
        twofa = config.TwoFAuthConfig(url="https://2fa.example.com", token="SECRET", account_id=1)
        prof = config.ProfileConfig(
            server="vpn.example.com", user_group="", name="Work", twofauth=twofa
        )
        cfg = config.Config()
        cfg.profiles["work"] = prof

        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = "work"
                file = None

            profiles._export_profile(Args())

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "SECRET" not in captured.out
        # Token should be removed from exported 2fauth section
        if "2fauth" in parsed["profile"]:
            assert "token" not in parsed["profile"]["2fauth"]

    def test_export_strips_password_from_credentials(self, capsys):
        creds = {"username": "alice", "totp_source": "local"}
        # We'll also stuff a 'password' into the dict to verify stripping
        data = {"server": "vpn.example.com", "credentials": creds}
        prof = config.ProfileConfig.from_dict(data)
        # Now artificially inject a password key by patching as_dict
        with patch.object(
            prof,
            "as_dict",
            return_value={
                "server": "vpn.example.com",
                "user_group": "",
                "name": "",
                "credentials": {
                    "username": "alice",
                    "password": "sekrit",
                    "totp": "abc",
                    "totp_secret": "xyz",
                    "totp_source": "local",
                },
            },
        ):
            cfg = config.Config()
            cfg.profiles["work"] = prof

            with patch("openconnect_saml.profiles.config.load", return_value=cfg):

                class Args:
                    profile_name = "work"
                    file = None

                profiles._export_profile(Args())

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        creds_out = parsed["profile"]["credentials"]
        assert "password" not in creds_out
        assert "totp" not in creds_out
        assert "totp_secret" not in creds_out
        # Username stays
        assert creds_out["username"] == "alice"


class TestNetworkManagerExport:
    def _args(self, **kw):
        defaults = {"profile_name": None, "file": None, "format": "nmconnection"}
        defaults.update(kw)
        return type("Args", (), defaults)()

    def test_export_nmconnection_to_stdout(self, capsys):
        cfg = _mk_cfg(
            {
                "work": {
                    "server": "vpn.example.com",
                    "user_group": "engineering",
                    "name": "Work",
                    "credentials": {"username": "alice@example.com"},
                }
            }
        )
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._export_profile(self._args(profile_name="work"))
        assert rc == 0
        out = capsys.readouterr().out
        assert "[connection]" in out
        assert "id=Work" in out
        assert "type=vpn" in out
        assert "service-type=org.freedesktop.NetworkManager.openconnect" in out
        assert "gateway=vpn.example.com" in out
        assert "usergroup=engineering" in out
        # Username goes into vpn-secrets
        assert "form:main:username=alice@example.com" in out
        # No raw passwords/tokens
        assert "password" not in out.lower() or "authtype=password" in out

    def test_export_nmconnection_strips_protocol_prefix(self, capsys):
        cfg = _mk_cfg(
            {"work": {"server": "https://vpn.example.com/", "user_group": "", "name": ""}}
        )
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            profiles._export_profile(self._args(profile_name="work"))
        out = capsys.readouterr().out
        assert "gateway=vpn.example.com" in out
        # Should not retain trailing slash or scheme
        assert "gateway=https://" not in out

    def test_export_nmconnection_stable_uuid(self, capsys):
        cfg = _mk_cfg({"work": {"server": "vpn.example.com"}})
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            profiles._export_profile(self._args(profile_name="work"))
            first = capsys.readouterr().out
            profiles._export_profile(self._args(profile_name="work"))
            second = capsys.readouterr().out
        # UUID is derived from the profile name, so re-exports must match.
        assert first == second
        assert "uuid=" in first

    def test_export_nmconnection_to_file(self, tmp_path):
        cfg = _mk_cfg({"work": {"server": "vpn.example.com"}})
        out = tmp_path / "work.nmconnection"
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._export_profile(self._args(profile_name="work", file=str(out)))
        assert rc == 0
        assert out.exists()
        # Mode 0600 since file may be installed under system-connections
        assert oct(out.stat().st_mode)[-3:] == "600"
        assert "[connection]" in out.read_text()

    def test_export_nmconnection_multiple_to_directory(self, tmp_path):
        cfg = _mk_cfg(
            {
                "work": {"server": "vpn.example.com"},
                "home": {"server": "home.example.com"},
            }
        )
        out_dir = tmp_path / "nm"
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._export_profile(self._args(file=str(out_dir)))
        assert rc == 0
        assert (out_dir / "work.nmconnection").exists()
        assert (out_dir / "home.nmconnection").exists()

    def test_export_nmconnection_multiple_to_stdout_fails(self, capsys):
        cfg = _mk_cfg(
            {
                "work": {"server": "vpn.example.com"},
                "home": {"server": "home.example.com"},
            }
        )
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._export_profile(self._args())
        assert rc == 1

    def test_export_nmconnection_missing_profile(self, capsys):
        cfg = _mk_cfg()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):
            rc = profiles._export_profile(self._args(profile_name="nope"))
        assert rc == 1


class TestImport:
    def test_import_from_file(self, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profile": {
                        "_name": "work",
                        "server": "vpn.example.com",
                        "user_group": "eng",
                        "name": "Work",
                    },
                }
            )
        )
        saved_cfg = {}

        def fake_save(cfg):
            saved_cfg["cfg"] = cfg

        cfg = config.Config()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save", side_effect=fake_save),
        ):

            class Args:
                file = str(f)
                as_name = None
                force = False

            rc = profiles._import_profile(Args())
        assert rc == 0
        assert "work" in saved_cfg["cfg"].profiles

    def test_import_refuses_overwrite_without_force(self, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "profile": {"_name": "work", "server": "vpn2.example.com"},
                }
            )
        )
        cfg = _mk_cfg({"work": {"server": "vpn.example.com"}})

        saved = []

        def fake_save(c):
            saved.append(c)

        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save", side_effect=fake_save),
        ):

            class Args:
                file = str(f)
                as_name = None
                force = False

            rc = profiles._import_profile(Args())
        # Nothing imported → rc == 1
        assert rc == 1
        # Config was not saved
        assert saved == []

    def test_import_with_force_overwrites(self, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "profile": {"_name": "work", "server": "vpn2.example.com"},
                }
            )
        )
        cfg = _mk_cfg({"work": {"server": "vpn.example.com"}})
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):

            class Args:
                file = str(f)
                as_name = None
                force = True

            rc = profiles._import_profile(Args())
        assert rc == 0
        assert cfg.profiles["work"].server == "vpn2.example.com"

    def test_import_rename_with_as(self, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "profile": {"_name": "work", "server": "vpn.example.com"},
                }
            )
        )
        cfg = config.Config()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):

            class Args:
                file = str(f)
                as_name = "workplace"
                force = False

            rc = profiles._import_profile(Args())
        assert rc == 0
        assert "workplace" in cfg.profiles
        assert "work" not in cfg.profiles

    def test_import_invalid_json(self, tmp_path):
        f = tmp_path / "in.json"
        f.write_text("this is not json")
        with patch("openconnect_saml.profiles.config.load", return_value=config.Config()):

            class Args:
                file = str(f)
                as_name = None
                force = False

            rc = profiles._import_profile(Args())
        assert rc == 1

    def test_import_multiple_profiles(self, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": {
                        "work": {"server": "vpn.example.com"},
                        "home": {"server": "home.example.com"},
                    },
                }
            )
        )
        cfg = config.Config()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):

            class Args:
                file = str(f)
                as_name = None
                force = False

            rc = profiles._import_profile(Args())
        assert rc == 0
        assert "work" in cfg.profiles
        assert "home" in cfg.profiles

    def test_import_as_with_multiple_fails(self, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "profiles": {
                        "a": {"server": "a.example.com"},
                        "b": {"server": "b.example.com"},
                    },
                }
            )
        )
        with patch("openconnect_saml.profiles.config.load", return_value=config.Config()):

            class Args:
                file = str(f)
                as_name = "renamed"
                force = False

            rc = profiles._import_profile(Args())
        assert rc == 1

    def test_import_bare_profile(self, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(
            json.dumps(
                {
                    "server": "vpn.example.com",
                    "_name": "work",
                }
            )
        )
        cfg = config.Config()
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):

            class Args:
                file = str(f)
                as_name = None
                force = False

            rc = profiles._import_profile(Args())
        assert rc == 0
        assert "work" in cfg.profiles


class TestRename:
    def test_rename(self, capsys):
        cfg = _mk_cfg({"work": {"server": "vpn.example.com"}})
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):

            class Args:
                profile_name = "work"
                new_name = "office"

            rc = profiles._rename_profile(Args())
        assert rc == 0
        assert "office" in cfg.profiles
        assert "work" not in cfg.profiles

    def test_rename_missing(self, capsys):
        cfg = config.Config()
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = "nope"
                new_name = "gone"

            rc = profiles._rename_profile(Args())
        assert rc == 1

    def test_rename_conflict(self):
        cfg = _mk_cfg(
            {
                "work": {"server": "w"},
                "home": {"server": "h"},
            }
        )
        with patch("openconnect_saml.profiles.config.load", return_value=cfg):

            class Args:
                profile_name = "work"
                new_name = "home"

            rc = profiles._rename_profile(Args())
        assert rc == 1

    def test_rename_updates_active(self):
        cfg = _mk_cfg({"work": {"server": "w"}}, active_profile="work")
        with (
            patch("openconnect_saml.profiles.config.load", return_value=cfg),
            patch("openconnect_saml.profiles.config.save"),
        ):

            class Args:
                profile_name = "work"
                new_name = "office"

            profiles._rename_profile(Args())
        assert cfg.active_profile == "office"
