"""Tests for multi-profile management."""

from unittest.mock import MagicMock, patch

from openconnect_saml.config import Config, HostProfile, ProfileConfig


class TestProfileConfig:
    """ProfileConfig creation and conversion."""

    def test_from_dict_basic(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "user_group": "employees",
                "name": "Work VPN",
            }
        )
        assert prof.server == "vpn.example.com"
        assert prof.user_group == "employees"
        assert prof.name == "Work VPN"
        assert prof.credentials is None

    def test_from_dict_with_credentials(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "user_group": "",
                "name": "Lab",
                "credentials": {"username": "admin", "totp_source": "2fauth"},
            }
        )
        assert prof.credentials is not None
        assert prof.credentials.username == "admin"
        assert prof.credentials.totp_source == "2fauth"

    def test_from_dict_none(self):
        assert ProfileConfig.from_dict(None) is None

    def test_to_host_profile(self):
        prof = ProfileConfig(server="vpn.example.com", user_group="group", name="Test")
        hp = prof.to_host_profile()
        assert isinstance(hp, HostProfile)
        assert hp.address == "vpn.example.com"
        assert hp.user_group == "group"

    def test_as_dict_roundtrip(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "user_group": "group",
                "name": "Test",
            }
        )
        d = prof.as_dict()
        assert d["server"] == "vpn.example.com"
        prof2 = ProfileConfig.from_dict(d)
        assert prof2.server == prof.server

    def test_with_2fauth(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "2fauth": {"url": "https://2fa.example.com", "token": "secret", "account_id": 1},
            }
        )
        assert prof.twofauth is not None
        assert prof.twofauth.url == "https://2fa.example.com"


class TestConfigProfiles:
    """Config multi-profile support."""

    def test_empty_profiles(self):
        cfg = Config()
        assert cfg.profiles == {}
        assert cfg.list_profiles() == []

    def test_add_profile(self):
        cfg = Config()
        cfg.add_profile(
            "work",
            {
                "server": "vpn.company.com",
                "user_group": "employees",
                "name": "Work VPN",
            },
        )
        assert "work" in cfg.profiles
        assert cfg.get_profile("work").server == "vpn.company.com"

    def test_add_profile_object(self):
        cfg = Config()
        prof = ProfileConfig(server="vpn.lab.com", user_group="", name="Lab")
        cfg.add_profile("lab", prof)
        assert cfg.get_profile("lab").server == "vpn.lab.com"

    def test_remove_profile(self):
        cfg = Config()
        cfg.add_profile("work", {"server": "vpn.company.com"})
        assert cfg.remove_profile("work") is True
        assert cfg.get_profile("work") is None

    def test_remove_nonexistent(self):
        cfg = Config()
        assert cfg.remove_profile("nonexistent") is False

    def test_list_profiles(self):
        cfg = Config()
        cfg.add_profile("work", {"server": "vpn.company.com", "name": "Work"})
        cfg.add_profile("lab", {"server": "lab-vpn.company.com", "name": "Lab"})
        profiles = cfg.list_profiles()
        assert len(profiles) == 2
        names = [n for n, _ in profiles]
        assert "work" in names
        assert "lab" in names

    def test_get_nonexistent(self):
        cfg = Config()
        assert cfg.get_profile("nonexistent") is None

    def test_from_dict_with_profiles(self):
        cfg = Config.from_dict(
            {
                "profiles": {
                    "work": {
                        "server": "vpn.company.com",
                        "user_group": "employees",
                        "name": "Work VPN",
                    },
                    "lab": {
                        "server": "lab.company.com",
                        "user_group": "",
                        "name": "Lab",
                    },
                },
                "active_profile": "work",
            }
        )
        assert len(cfg.profiles) == 2
        assert cfg.active_profile == "work"
        assert cfg.get_profile("work").server == "vpn.company.com"

    def test_as_dict_with_profiles(self):
        cfg = Config()
        cfg.add_profile("work", {"server": "vpn.company.com", "name": "Work"})
        d = cfg.as_dict()
        assert "profiles" in d
        assert "work" in d["profiles"]

    def test_backwards_compat_no_profiles(self):
        """Config without profiles section still works."""
        cfg = Config.from_dict(
            {
                "default_profile": {
                    "address": "vpn.old.com",
                    "user_group": "",
                    "name": "old",
                }
            }
        )
        assert cfg.default_profile is not None
        assert cfg.default_profile.address == "vpn.old.com"
        assert cfg.profiles == {}

    def test_update_existing_profile(self):
        cfg = Config()
        cfg.add_profile("work", {"server": "old.com"})
        cfg.add_profile("work", {"server": "new.com"})
        assert cfg.get_profile("work").server == "new.com"
        assert len(cfg.profiles) == 1


class TestProfilesCLI:
    """Test profiles CLI handlers."""

    @patch("openconnect_saml.profiles.config")
    def test_list_empty(self, mock_config, capsys):
        from openconnect_saml.profiles import handle_profiles_command

        mock_cfg = Config()
        mock_config.load.return_value = mock_cfg

        args = MagicMock()
        args.profiles_action = None
        result = handle_profiles_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "No profiles" in captured.out

    @patch("openconnect_saml.profiles.config")
    def test_list_with_profiles(self, mock_config, capsys):
        from openconnect_saml.profiles import handle_profiles_command

        mock_cfg = Config()
        mock_cfg.add_profile("work", {"server": "vpn.company.com", "name": "Work"})
        mock_config.load.return_value = mock_cfg

        args = MagicMock()
        args.profiles_action = None
        result = handle_profiles_command(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "work" in captured.out
        assert "vpn.company.com" in captured.out

    @patch("openconnect_saml.profiles.config")
    def test_add_profile_noninteractive(self, mock_config, capsys):
        from openconnect_saml.profiles import handle_profiles_command

        mock_cfg = Config()
        mock_config.load.return_value = mock_cfg

        args = MagicMock()
        args.profiles_action = "add"
        args.profile_name = "test"
        args.server = "vpn.test.com"
        args.user_group = "group"
        args.display_name = "Test VPN"
        args.user = "testuser"
        args.totp_source = None

        result = handle_profiles_command(args)
        assert result == 0
        mock_config.save.assert_called_once()
        captured = capsys.readouterr()
        assert "Added" in captured.out

    @patch("openconnect_saml.profiles.config")
    def test_remove_profile_exists(self, mock_config, capsys):
        from openconnect_saml.profiles import handle_profiles_command

        mock_cfg = Config()
        mock_cfg.add_profile("work", {"server": "vpn.company.com"})
        mock_config.load.return_value = mock_cfg

        args = MagicMock()
        args.profiles_action = "remove"
        args.profile_name = "work"

        result = handle_profiles_command(args)
        assert result == 0
        mock_config.save.assert_called_once()
        captured = capsys.readouterr()
        assert "Removed" in captured.out

    @patch("openconnect_saml.profiles.config")
    def test_remove_profile_not_found(self, mock_config, capsys):
        from openconnect_saml.profiles import handle_profiles_command

        mock_cfg = Config()
        mock_config.load.return_value = mock_cfg

        args = MagicMock()
        args.profiles_action = "remove"
        args.profile_name = "nonexistent"

        result = handle_profiles_command(args)
        assert result == 1
