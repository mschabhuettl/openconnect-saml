"""Tests for per-profile setting overrides introduced in v0.11.0."""

from __future__ import annotations

from openconnect_saml.config import (
    SCHEMA_VERSION,
    Config,
    KillSwitchSettings,
    ProfileConfig,
)


class TestSchemaVersion:
    def test_default_schema_version(self):
        cfg = Config()
        assert cfg.schema_version == SCHEMA_VERSION

    def test_explicit_schema_version_preserved(self):
        cfg = Config(schema_version=42)
        assert cfg.schema_version == 42

    def test_serializes_schema_version(self):
        cfg = Config(schema_version=1)
        d = cfg.as_dict()
        assert d["schema_version"] == 1


class TestProfileBrowserOverride:
    def test_default_is_none(self):
        prof = ProfileConfig(server="vpn.example.com")
        assert prof.browser is None

    def test_can_set_browser(self):
        prof = ProfileConfig(server="vpn.example.com", browser="chrome")
        assert prof.browser == "chrome"

    def test_round_trip_dict(self):
        prof = ProfileConfig.from_dict({"server": "vpn.example.com", "browser": "qt"})
        assert prof.browser == "qt"
        assert prof.as_dict()["browser"] == "qt"

    def test_none_browser_omitted_from_dict(self):
        prof = ProfileConfig(server="vpn.example.com")
        d = prof.as_dict()
        assert "browser" not in d


class TestProfileNotifyOverride:
    def test_default_is_none(self):
        prof = ProfileConfig(server="vpn.example.com")
        assert prof.notify is None

    def test_can_set_true(self):
        prof = ProfileConfig.from_dict({"server": "vpn.example.com", "notify": True})
        assert prof.notify is True

    def test_can_set_false(self):
        prof = ProfileConfig.from_dict({"server": "vpn.example.com", "notify": False})
        assert prof.notify is False

    def test_explicit_false_round_trips(self):
        prof = ProfileConfig.from_dict({"server": "vpn.example.com", "notify": False})
        # False is meaningful — should not be dropped as if it were None.
        assert prof.as_dict().get("notify") is False


class TestProfileHooks:
    def test_on_connect_default_none(self):
        prof = ProfileConfig(server="vpn.example.com")
        assert prof.on_connect is None
        assert prof.on_disconnect is None

    def test_on_connect_set(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "on_connect": "/usr/local/bin/route-add",
                "on_disconnect": "/usr/local/bin/route-cleanup",
            }
        )
        assert prof.on_connect == "/usr/local/bin/route-add"
        assert prof.on_disconnect == "/usr/local/bin/route-cleanup"


class TestProfileKillSwitch:
    def test_default_none(self):
        prof = ProfileConfig(server="vpn.example.com")
        assert prof.kill_switch is None

    def test_per_profile_kill_switch(self):
        prof = ProfileConfig.from_dict(
            {
                "server": "vpn.example.com",
                "kill_switch": {"enabled": True, "allow_lan": True, "ipv6": False},
            }
        )
        assert isinstance(prof.kill_switch, KillSwitchSettings)
        assert prof.kill_switch.enabled is True
        assert prof.kill_switch.allow_lan is True
        assert prof.kill_switch.ipv6 is False

    def test_per_profile_kill_switch_overrides_global(self):
        cfg = Config(
            kill_switch={"enabled": False, "allow_lan": False},
        )
        cfg.add_profile(
            "work",
            {
                "server": "vpn.example.com",
                "kill_switch": {"enabled": True, "allow_lan": True},
            },
        )
        prof = cfg.get_profile("work")
        # Per-profile object should be its own KillSwitchSettings instance
        assert prof.kill_switch is not None
        assert prof.kill_switch.enabled is True
        assert cfg.kill_switch.enabled is False
