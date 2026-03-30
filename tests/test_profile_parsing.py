"""Tests for profile XML parsing — valid, invalid, edge cases."""

import pytest

from openconnect_saml.profile import _get_profiles_from_one_file, get_profiles


class TestValidProfiles:
    def test_single_host_entry(self, tmp_path):
        profile = tmp_path / "test.xml"
        profile.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>Test VPN</HostName>
      <HostAddress>vpn.example.com</HostAddress>
      <UserGroup>group1</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>""")
        profiles = _get_profiles_from_one_file(profile)
        assert len(profiles) == 1
        assert profiles[0].name == "Test VPN"
        assert profiles[0].address == "vpn.example.com"

    def test_multiple_host_entries(self, tmp_path):
        profile = tmp_path / "test.xml"
        profile.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>VPN 1</HostName>
      <HostAddress>vpn1.example.com</HostAddress>
      <UserGroup>group1</UserGroup>
    </HostEntry>
    <HostEntry>
      <HostName>VPN 2</HostName>
      <HostAddress>vpn2.example.com</HostAddress>
      <UserGroup>group2</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>""")
        profiles = _get_profiles_from_one_file(profile)
        assert len(profiles) == 2


class TestInvalidProfiles:
    def test_corrupt_xml(self, tmp_path):
        profile = tmp_path / "corrupt.xml"
        profile.write_text("this is not xml at all!!!")
        profiles = _get_profiles_from_one_file(profile)
        assert profiles == []

    def test_empty_file(self, tmp_path):
        profile = tmp_path / "empty.xml"
        profile.write_text("")
        profiles = _get_profiles_from_one_file(profile)
        assert profiles == []

    def test_valid_xml_no_entries(self, tmp_path):
        profile = tmp_path / "noentries.xml"
        profile.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList/>
</AnyConnectProfile>""")
        profiles = _get_profiles_from_one_file(profile)
        assert profiles == []


class TestGetProfiles:
    def test_from_file(self, tmp_path):
        profile = tmp_path / "test.xml"
        profile.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>Test</HostName>
      <HostAddress>vpn.test.com</HostAddress>
      <UserGroup>grp</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>""")
        profiles = get_profiles(profile)
        assert len(profiles) == 1

    def test_from_directory(self, tmp_path):
        for i in range(3):
            (tmp_path / f"profile{i}.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>VPN {i}</HostName>
      <HostAddress>vpn{i}.test.com</HostAddress>
      <UserGroup>grp</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>""")
        profiles = get_profiles(tmp_path)
        assert len(profiles) == 3

    def test_nonexistent_path(self, tmp_path):
        with pytest.raises(ValueError, match="No profile file found"):
            get_profiles(tmp_path / "nonexistent")

    def test_empty_directory(self, tmp_path):
        profiles = get_profiles(tmp_path)
        assert profiles == []
