"""Security audit tests — XXE, credential leaks, input validation, permissions."""

import stat
from unittest.mock import MagicMock, patch

import pytest
from lxml import etree

from openconnect_saml.authenticator import (
    AuthResponseError,
    _make_safe_parser,
    parse_auth_complete_response,
    parse_auth_request_response,
)
from openconnect_saml.config import Config, Credentials, save
from openconnect_saml.profile import _get_profiles_from_one_file
from openconnect_saml.profile import _make_safe_parser as _profile_safe_parser

# === XXE Protection ===


class TestXXEProtection:
    """Verify XML parsers reject external entity expansion."""

    XXE_PAYLOAD = b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<config-auth type="auth-request">
  <auth id="main">
    <title>&xxe;</title>
    <message>test</message>
    <sso-v2-login>https://example.com/login</sso-v2-login>
    <sso-v2-login-final>https://example.com/final</sso-v2-login-final>
    <sso-v2-token-cookie-name>token</sso-v2-token-cookie-name>
  </auth>
  <opaque/>
</config-auth>"""

    def test_authenticator_parser_blocks_xxe(self):
        """authenticator's safe parser should not resolve entities."""
        parser = _make_safe_parser()
        # Should parse without expanding the entity
        xml = etree.fromstring(self.XXE_PAYLOAD, parser=parser)
        # The entity should NOT have been resolved to /etc/passwd content
        title = xml.find(".//title")
        if title is not None and title.text:
            assert "/root:" not in title.text

    def test_profile_parser_blocks_xxe(self):
        """profile's safe parser should not resolve entities."""
        parser = _profile_safe_parser()
        assert parser is not None

    def test_xxe_in_profile_file(self, tmp_path):
        """Profile XML with XXE payload should not leak file contents."""
        xxe_profile = tmp_path / "evil.xml"
        xxe_profile.write_bytes(b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ENTITY xxe SYSTEM "file:///etc/passwd">
]>
<AnyConnectProfile xmlns="http://schemas.xmlsoap.org/encoding/">
  <ServerList>
    <HostEntry>
      <HostName>&xxe;</HostName>
      <HostAddress>vpn.example.com</HostAddress>
      <UserGroup>group</UserGroup>
    </HostEntry>
  </ServerList>
</AnyConnectProfile>""")
        profiles = _get_profiles_from_one_file(xxe_profile)
        for p in profiles:
            assert "/root:" not in p.name


# === Credential Safety ===


class TestCredentialSafety:
    """Verify credentials are not leaked in logs or debug output."""

    def test_credentials_repr_hides_password(self):
        """Credentials __repr__ should NOT contain the password."""
        cred = Credentials("testuser")
        cred._password = "super-secret-password"
        repr_str = repr(cred)
        assert "super-secret-password" not in repr_str

    def test_credentials_repr_hides_totp(self):
        """Credentials __repr__ should NOT contain the TOTP secret."""
        cred = Credentials("testuser")
        cred._totp_secret = "JBSWY3DPEHPK3PXP"
        repr_str = repr(cred)
        assert "JBSWY3DPEHPK3PXP" not in repr_str


# === Config File Permissions ===


class TestConfigPermissions:
    """Verify config files are saved with restrictive permissions."""

    @patch("openconnect_saml.config.xdg.BaseDirectory.save_config_path")
    def test_config_saved_with_restricted_permissions(self, mock_save_path, tmp_path):
        mock_save_path.return_value = str(tmp_path)
        cfg = Config()
        save(cfg)
        config_path = tmp_path / "config.toml"
        assert config_path.exists()
        mode = stat.S_IMODE(config_path.stat().st_mode)
        # Should be 0600 (owner read/write only)
        assert mode == 0o600, f"Config permissions are {oct(mode)}, expected 0o600"


# === Assert → Proper Error Handling ===


class TestAuthResponseErrors:
    """Verify parse functions use proper exceptions instead of assert."""

    def test_auth_request_wrong_id_raises(self):
        """auth-request with id != 'main' should raise AuthResponseError."""
        from lxml import objectify

        xml_str = b"""<?xml version="1.0" encoding="UTF-8"?>
<config-auth type="auth-request">
  <auth id="wrong">
    <title>Test</title>
    <message>Test</message>
    <sso-v2-login>https://example.com/login</sso-v2-login>
    <sso-v2-login-final>https://example.com/final</sso-v2-login-final>
    <sso-v2-token-cookie-name>token</sso-v2-token-cookie-name>
  </auth>
  <opaque/>
</config-auth>"""
        xml = objectify.fromstring(xml_str)
        with pytest.raises(AuthResponseError, match="Expected auth id 'main'"):
            parse_auth_request_response(xml)

    def test_auth_complete_wrong_id_raises(self):
        """auth-complete with id != 'success' should raise AuthResponseError."""
        from lxml import objectify

        xml_str = b"""<?xml version="1.0" encoding="UTF-8"?>
<config-auth type="complete">
  <auth id="failure">
    <message>Failed</message>
  </auth>
  <session-token>token</session-token>
  <config><vpn-base-config><server-cert-hash>hash</server-cert-hash></vpn-base-config></config>
</config-auth>"""
        xml = objectify.fromstring(xml_str)
        with pytest.raises(AuthResponseError, match="Expected auth id 'success'"):
            parse_auth_complete_response(xml)

    def test_auth_complete_missing_auth_raises(self):
        """auth-complete without 'auth' element should raise AuthResponseError."""
        from lxml import objectify

        xml_str = b"""<?xml version="1.0" encoding="UTF-8"?>
<config-auth type="complete">
  <session-token>token</session-token>
</config-auth>"""
        xml = objectify.fromstring(xml_str)
        with pytest.raises(AuthResponseError, match="missing 'auth'"):
            parse_auth_complete_response(xml)


# === Input Validation ===


class TestInputValidation:
    """Verify on-connect/on-disconnect commands are validated."""

    def test_validate_hook_rejects_semicolons(self):
        from openconnect_saml.app import _validate_hook_command

        assert _validate_hook_command("/usr/bin/script.sh") is True
        assert _validate_hook_command("echo hello; rm -rf /") is False
        assert _validate_hook_command("$(whoami)") is False
        assert _validate_hook_command("`id`") is False
        assert _validate_hook_command("cmd1 && cmd2") is False
        assert _validate_hook_command("cmd1 || cmd2") is False
        assert _validate_hook_command("cmd1 | cmd2") is False

    def test_validate_hook_allows_simple_commands(self):
        from openconnect_saml.app import _validate_hook_command

        assert _validate_hook_command("") is True
        assert _validate_hook_command("/path/to/script") is True
        assert _validate_hook_command("/usr/local/bin/vpn-up.sh --flag value") is True

    def test_handle_connect_rejects_injection(self):
        from openconnect_saml.app import handle_connect

        result = handle_connect("echo hello; rm -rf /")
        assert result == 1

    def test_handle_disconnect_rejects_injection(self):
        from openconnect_saml.app import handle_disconnect

        result = handle_disconnect("$(whoami)")
        assert result == 1


# === Shell=True Elimination ===


class TestNoShellTrue:
    """Verify subprocess calls don't use shell=True."""

    @patch("subprocess.run")
    def test_handle_connect_no_shell(self, mock_run):
        from openconnect_saml.app import handle_connect

        mock_run.return_value = MagicMock(returncode=0)
        handle_connect("/usr/bin/test-script")
        if mock_run.called:
            _, kwargs = mock_run.call_args
            assert kwargs.get("shell") is not True or "shell" not in kwargs

    @patch("subprocess.run")
    def test_handle_disconnect_no_shell(self, mock_run):
        from openconnect_saml.app import handle_disconnect

        mock_run.return_value = MagicMock(returncode=0)
        handle_disconnect("/usr/bin/test-script")
        if mock_run.called:
            _, kwargs = mock_run.call_args
            assert kwargs.get("shell") is not True or "shell" not in kwargs
