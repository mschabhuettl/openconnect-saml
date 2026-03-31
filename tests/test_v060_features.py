"""Tests for v0.6.0 features: CLI args, config changes, integration."""

from openconnect_saml import config
from openconnect_saml.cli import create_argparser, create_legacy_argparser


class TestCLINewArgs:
    """Test new CLI arguments for v0.6.0."""

    def test_notify_flag(self):
        parser = create_argparser()
        args = parser.parse_args(["connect", "--server", "vpn.example.com", "--notify"])
        assert args.notify is True

    def test_notify_default_off(self):
        parser = create_argparser()
        args = parser.parse_args(["connect", "--server", "vpn.example.com"])
        assert args.notify is False

    def test_totp_source_bitwarden(self):
        parser = create_argparser()
        args = parser.parse_args(
            [
                "connect",
                "--server",
                "vpn.example.com",
                "--totp-source",
                "bitwarden",
                "--bw-item-id",
                "abc-123",
            ]
        )
        assert args.totp_source == "bitwarden"
        assert args.bw_item_id == "abc-123"

    def test_bw_item_id_default(self):
        parser = create_argparser()
        args = parser.parse_args(["connect", "--server", "vpn.example.com"])
        assert args.bw_item_id is None

    def test_route_args(self):
        parser = create_argparser()
        args = parser.parse_args(
            [
                "connect",
                "--server",
                "vpn.example.com",
                "--route",
                "10.0.0.0/8",
                "--no-route",
                "192.168.0.0/16",
            ]
        )
        assert args.routes == ["10.0.0.0/8"]
        assert args.no_routes == ["192.168.0.0/16"]

    def test_multiple_routes(self):
        parser = create_argparser()
        args = parser.parse_args(
            [
                "connect",
                "--server",
                "vpn.example.com",
                "--route",
                "10.0.0.0/8",
                "--route",
                "172.16.0.0/12",
            ]
        )
        assert args.routes == ["10.0.0.0/8", "172.16.0.0/12"]

    def test_setup_subcommand(self):
        parser = create_argparser()
        args = parser.parse_args(["setup"])
        assert args.command == "setup"

    def test_legacy_args_with_routes(self):
        parser = create_legacy_argparser()
        args = parser.parse_args(
            [
                "--server",
                "vpn.example.com",
                "--route",
                "10.0.0.0/8",
                "--notify",
            ]
        )
        assert args.routes == ["10.0.0.0/8"]
        assert args.notify is True


class TestConfigNotifications:
    def test_notifications_default(self):
        cfg = config.Config()
        assert cfg.notifications is False

    def test_notifications_enabled(self):
        cfg = config.Config(notifications=True)
        assert cfg.notifications is True

    def test_notifications_from_dict(self):
        cfg = config.Config.from_dict({"notifications": True})
        assert cfg.notifications is True

    def test_notifications_serialization(self):
        cfg = config.Config(notifications=True)
        d = cfg.as_dict()
        assert d["notifications"] is True


class TestConfigBitwarden:
    def test_bitwarden_default(self):
        cfg = config.Config()
        assert cfg.bitwarden is None

    def test_bitwarden_from_dict(self):
        cfg = config.Config.from_dict(
            {
                "bitwarden": {"item_id": "abc-123"},
            }
        )
        assert cfg.bitwarden is not None
        assert cfg.bitwarden.item_id == "abc-123"

    def test_bitwarden_serialization(self):
        cfg = config.Config(bitwarden=config.BitwardenConfig(item_id="abc-123"))
        d = cfg.as_dict()
        assert "bitwarden" in d
        assert d["bitwarden"]["item_id"] == "abc-123"


class TestConfigRoutes:
    def test_profile_routes_roundtrip(self):
        """Routes survive config save/load cycle."""
        prof = config.ProfileConfig(
            server="vpn.example.com",
            routes=["10.0.0.0/8"],
            no_routes=["192.168.0.0/16"],
        )
        d = prof.as_dict()
        restored = config.ProfileConfig.from_dict(d)
        assert restored.routes == ["10.0.0.0/8"]
        assert restored.no_routes == ["192.168.0.0/16"]


class TestIsLegacyInvocation:
    def test_setup_is_not_legacy(self):
        from openconnect_saml.cli import _is_legacy_invocation

        assert _is_legacy_invocation(["setup"]) is False

    def test_connect_is_not_legacy(self):
        from openconnect_saml.cli import _is_legacy_invocation

        assert _is_legacy_invocation(["connect"]) is False

    def test_flag_is_legacy(self):
        from openconnect_saml.cli import _is_legacy_invocation

        assert _is_legacy_invocation(["--server", "vpn.example.com"]) is True
