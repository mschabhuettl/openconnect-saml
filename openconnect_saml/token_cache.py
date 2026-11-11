"""VPN session cookies stored separately from passwords in the OS keyring."""

import contextlib
import hashlib
import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import keyring
import keyring.errors
import structlog

from openconnect_saml.authenticator import AuthCompleteResponse

logger = structlog.get_logger()
SERVICE = "openconnect-saml/session"


@dataclass
class SavedSession:
    response: AuthCompleteResponse = field(repr=False)
    vpn_url: str


def cache_key(host, username="", profile=""):
    identity = [host.vpn_url, host.user_group, host.name, username or "", profile or ""]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def load(key):
    try:
        value = keyring.get_password(SERVICE, key)
        if not value:
            return None
        data = json.loads(value)
        if not all(
            isinstance(data.get(k), str) and data[k] for k in ("cookie", "fingerprint", "vpn_url")
        ):
            return None
        target = urlsplit(data["vpn_url"])
        if target.scheme not in ("https", "http") or not target.hostname or target.username:
            return None
        return SavedSession(
            AuthCompleteResponse(
                "success", "Using saved VPN session", data["cookie"], data["fingerprint"]
            ),
            data["vpn_url"],
        )
    except (keyring.errors.KeyringError, ValueError, TypeError, AttributeError):
        logger.info("Saved VPN session unavailable; using SSO")
        return None


def save(key, response, host):
    try:
        keyring.set_password(
            SERVICE,
            key,
            json.dumps(
                {
                    "cookie": response.session_token,
                    "fingerprint": response.server_cert_hash,
                    # Authentication can redirect to a different gateway. Its
                    # cookie and certificate pin must be reused with that URL.
                    "vpn_url": host.vpn_url,
                }
            ),
        )
    except keyring.errors.KeyringError:
        logger.warning("Cannot save VPN session to keyring; next connection will use SSO")


def delete(key):
    with contextlib.suppress(keyring.errors.KeyringError):
        keyring.delete_password(SERVICE, key)
