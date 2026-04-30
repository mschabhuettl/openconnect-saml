"""Tests for `profiles import-xml` (Cisco AnyConnect XML import)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from openconnect_saml import config, profiles

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>EU VPN</HostName>
      <HostAddress>vpn-eu.example.com</HostAddress>
      <UserGroup>employees</UserGroup>
    </HostEntry>
    <HostEntry>
      <HostName>US VPN</HostName>
      <HostAddress>vpn-us.example.com</HostAddress>
      <UserGroup>contractors</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>
"""


def _args(file, force=False, prefix=""):
    return SimpleNamespace(file=file, force=force, prefix=prefix)


def test_import_xml_creates_profiles(tmp_path, capsys):
    xml = tmp_path / "anyconnect.xml"
    xml.write_text(SAMPLE_XML)

    cfg = config.Config()
    saved = []
    with (
        patch("openconnect_saml.profiles.config.load", return_value=cfg),
        patch("openconnect_saml.profiles.config.save", side_effect=saved.append),
    ):
        rc = profiles._import_xml_profile(_args(str(xml)))

    assert rc == 0
    assert "EU_VPN" in cfg.profiles
    assert "US_VPN" in cfg.profiles
    assert cfg.profiles["EU_VPN"].server == "vpn-eu.example.com"
    assert cfg.profiles["EU_VPN"].user_group == "employees"
    assert saved, "config.save should have been called"


def test_import_xml_with_prefix(tmp_path):
    xml = tmp_path / "anyconnect.xml"
    xml.write_text(SAMPLE_XML)
    cfg = config.Config()
    with (
        patch("openconnect_saml.profiles.config.load", return_value=cfg),
        patch("openconnect_saml.profiles.config.save"),
    ):
        profiles._import_xml_profile(_args(str(xml), prefix="cisco-"))
    assert "cisco-EU_VPN" in cfg.profiles
    assert "cisco-US_VPN" in cfg.profiles


def test_import_xml_skips_existing_without_force(tmp_path, capsys):
    xml = tmp_path / "anyconnect.xml"
    xml.write_text(SAMPLE_XML)
    cfg = config.Config()
    cfg.add_profile("EU_VPN", {"server": "old.example.com"})
    with (
        patch("openconnect_saml.profiles.config.load", return_value=cfg),
        patch("openconnect_saml.profiles.config.save"),
    ):
        profiles._import_xml_profile(_args(str(xml)))
    # Existing record was kept
    assert cfg.profiles["EU_VPN"].server == "old.example.com"


def test_import_xml_force_overwrites(tmp_path):
    xml = tmp_path / "anyconnect.xml"
    xml.write_text(SAMPLE_XML)
    cfg = config.Config()
    cfg.add_profile("EU_VPN", {"server": "old.example.com"})
    with (
        patch("openconnect_saml.profiles.config.load", return_value=cfg),
        patch("openconnect_saml.profiles.config.save"),
    ):
        profiles._import_xml_profile(_args(str(xml), force=True))
    assert cfg.profiles["EU_VPN"].server == "vpn-eu.example.com"


def test_import_xml_missing_file(tmp_path, capsys):
    rc = profiles._import_xml_profile(_args(str(tmp_path / "no.xml")))
    assert rc == 1


def test_import_xml_no_host_entries(tmp_path):
    xml = tmp_path / "empty.xml"
    xml.write_text(
        '<?xml version="1.0"?><AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/"/>'
    )
    rc = profiles._import_xml_profile(_args(str(xml)))
    assert rc == 1
