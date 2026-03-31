"""TOTP provider abstraction — local (pyotp/keyring), remote (2FAuth API), or Bitwarden CLI.

Providers:
- ``LocalTotpProvider``: generates TOTP locally from a secret stored in
  keyring or memory (the original behaviour).
- ``TwoFAuthProvider``: fetches a one-time password from a
  `2FAuth <https://docs.2fauth.app/>`_ instance via its REST API.
- ``BitwardenProvider``: fetches a TOTP code from Bitwarden via the ``bw`` CLI.
"""

from __future__ import annotations

import abc
import binascii
import os
import shutil
import subprocess  # nosec
from urllib.parse import urlparse

import keyring
import keyring.errors
import pyotp
import requests
import structlog

logger = structlog.get_logger()

APP_NAME = "openconnect-saml"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class TotpProvider(abc.ABC):
    """Abstract base for TOTP providers."""

    @abc.abstractmethod
    def get_totp(self) -> str | None:
        """Return a current TOTP code, or *None* on failure."""


# ---------------------------------------------------------------------------
# Local provider (pyotp + keyring) — mirrors the old Credentials.totp logic
# ---------------------------------------------------------------------------


class LocalTotpProvider(TotpProvider):
    """Generate TOTP locally from a stored secret.

    Parameters
    ----------
    username : str
        Keyring lookup key.
    totp_secret : str or None
        In-memory secret; falls back to keyring.
    """

    def __init__(self, username: str, totp_secret: str | None = None):
        self.username = username
        self._totp_secret = totp_secret

    def get_totp(self) -> str | None:
        secret = self._totp_secret

        if not secret:
            try:
                secret = keyring.get_password(APP_NAME, "totp/" + self.username)
            except keyring.errors.KeyringError:
                logger.info("Cannot retrieve saved totp info from keyring.")
                return ""

        if not secret:
            return None

        try:
            return pyotp.TOTP(secret).now()
        except (binascii.Error, ValueError) as exc:
            logger.warning(
                "Corrupt TOTP secret (#143), ignoring.",
                error=str(exc),
            )
            self._totp_secret = None
            return None
        except Exception:
            logger.warning("Invalid TOTP secret, ignoring")
            return None


# ---------------------------------------------------------------------------
# 2FAuth remote provider
# ---------------------------------------------------------------------------


class TwoFAuthError(Exception):
    """Raised when the 2FAuth API call fails."""


class TwoFAuthProvider(TotpProvider):
    """Fetch TOTP from a 2FAuth instance.

    Parameters
    ----------
    url : str
        Base URL of the 2FAuth instance (e.g. ``https://2fauth.example.com``).
    token : str
        Personal Access Token for the 2FAuth API.
    account_id : int
        ID of the 2FA account entry to query.
    timeout : int
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        url: str,
        token: str,
        account_id: int,
        timeout: int = 10,
    ):
        self.url = url.rstrip("/")
        self.token = token
        self.account_id = account_id
        self.timeout = timeout
        self._warn_if_insecure()

    def _warn_if_insecure(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https":
            logger.warning(
                "2FAuth URL uses insecure HTTP — tokens are sent in plain text!",
                url=self.url,
            )

    def get_totp(self) -> str | None:
        endpoint = f"{self.url}/api/v1/twofaccounts/{self.account_id}/otp"
        logger.info("Fetching TOTP from 2FAuth...")

        try:
            resp = requests.get(
                endpoint,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout:
            logger.error("2FAuth request timed out")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to 2FAuth instance", url=self.url)
            return None
        except requests.exceptions.RequestException as exc:
            logger.error("2FAuth request failed", error=str(exc))
            return None

        if resp.status_code == 401:
            logger.error("2FAuth authentication failed — check your Personal Access Token")
            return None
        if resp.status_code == 404:
            logger.error(
                "2FAuth account not found",
                account_id=self.account_id,
            )
            return None
        if resp.status_code != 200:
            logger.error(
                "2FAuth returned unexpected status",
                status=resp.status_code,
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.error("2FAuth returned invalid JSON")
            return None

        otp = data.get("password")
        if not otp:
            logger.error("2FAuth response missing 'password' field")
            return None

        logger.info("TOTP fetched from 2FAuth successfully")
        return str(otp)


# ---------------------------------------------------------------------------
# Bitwarden CLI provider
# ---------------------------------------------------------------------------


class BitwardenError(Exception):
    """Raised when the Bitwarden CLI call fails."""


class BitwardenProvider(TotpProvider):
    """Fetch TOTP from Bitwarden via the ``bw`` CLI.

    Requires the Bitwarden CLI (``bw``) to be installed and either a session
    key in ``BW_SESSION`` or an unlocked vault.

    Parameters
    ----------
    item_id : str
        UUID of the Bitwarden vault item containing the TOTP secret.
    timeout : int
        CLI command timeout in seconds.
    """

    def __init__(self, item_id: str, timeout: int = 10):
        self.item_id = item_id
        self.timeout = timeout

    def get_totp(self) -> str | None:
        bw_path = shutil.which("bw")
        if not bw_path:
            logger.error("Bitwarden CLI (bw) not found in PATH")
            return None

        logger.info("Fetching TOTP from Bitwarden CLI...")

        env = dict(os.environ)
        # BW_SESSION may already be set in the environment

        try:
            result = subprocess.run(  # nosec
                [bw_path, "get", "totp", self.item_id],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            logger.error("Bitwarden CLI timed out", timeout=self.timeout)
            return None
        except FileNotFoundError:
            logger.error("Bitwarden CLI (bw) not found")
            return None
        except OSError as exc:
            logger.error("Bitwarden CLI failed", error=str(exc))
            return None

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "locked" in stderr.lower() or "not logged in" in stderr.lower():
                logger.error(
                    "Bitwarden vault is locked or not logged in. "
                    "Run 'bw unlock' and export BW_SESSION, or 'bw login' first."
                )
            elif "not found" in stderr.lower():
                logger.error(
                    "Bitwarden item not found",
                    item_id=self.item_id,
                )
            else:
                logger.error(
                    "Bitwarden CLI returned error",
                    exit_code=result.returncode,
                    stderr=stderr,
                )
            return None

        otp = result.stdout.strip()
        if not otp:
            logger.error("Bitwarden CLI returned empty TOTP")
            return None

        logger.info("TOTP fetched from Bitwarden successfully")
        return otp
