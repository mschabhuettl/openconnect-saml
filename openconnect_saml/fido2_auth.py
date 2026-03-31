"""FIDO2/WebAuthn authentication support for openconnect-saml.

Handles FIDO2 security key challenges during SAML authentication flows.
Supports USB HID devices (YubiKey, SoloKey, etc.) via the python-fido2 library.

Install with: pip install openconnect-saml[fido2]
"""

from __future__ import annotations

import sys
from typing import Any

import structlog

logger = structlog.get_logger()

# Default timeout for user interaction (touching the key)
DEFAULT_FIDO2_TIMEOUT = 30  # seconds


class FIDO2AuthError(Exception):
    """Raised when FIDO2 authentication fails."""


class FIDO2Authenticator:
    """Handle FIDO2/WebAuthn challenges using a hardware security key.

    Parameters
    ----------
    timeout : int
        Seconds to wait for user to touch the security key.
    """

    def __init__(self, timeout: int = DEFAULT_FIDO2_TIMEOUT):
        self.timeout = timeout
        self._client = None
        self._device = None

    def _ensure_fido2(self):
        """Lazily import fido2 and detect a device."""
        try:
            from fido2.hid import CtapHidDevice
        except ImportError as exc:
            raise FIDO2AuthError(
                "python-fido2 is not installed. Install with: pip install openconnect-saml[fido2]"
            ) from exc
        return CtapHidDevice

    def detect_device(self) -> bool:
        """Check if a FIDO2 device is connected.

        Returns True if at least one device is found.
        """
        CtapHidDevice = self._ensure_fido2()

        devices = list(CtapHidDevice.list_devices())
        if not devices:
            logger.warning("No FIDO2 devices found")
            return False

        self._device = devices[0]
        logger.info(
            "FIDO2 device detected",
            device=str(self._device),
            count=len(devices),
        )
        return True

    def authenticate(
        self,
        challenge: bytes,
        rp_id: str,
        credential_ids: list[bytes] | None = None,
        user_verification: str = "discouraged",
    ) -> dict[str, Any]:
        """Perform a FIDO2 assertion (authentication).

        Parameters
        ----------
        challenge : bytes
            The challenge from the server.
        rp_id : str
            The relying party ID (usually the domain).
        credential_ids : list[bytes] or None
            List of allowed credential IDs.
        user_verification : str
            User verification requirement (discouraged/preferred/required).

        Returns
        -------
        dict
            The assertion response containing authenticatorData, clientDataJSON,
            and signature.
        """
        try:
            from fido2.client import Fido2Client, UserInteraction
            from fido2.webauthn import PublicKeyCredentialDescriptor, PublicKeyCredentialType
        except ImportError as exc:
            raise FIDO2AuthError(
                "python-fido2 is not installed. Install with: pip install openconnect-saml[fido2]"
            ) from exc

        if not self._device and not self.detect_device():
            raise FIDO2AuthError("No FIDO2 security key detected. Please insert your key.")

        # User interaction handler
        class CliInteraction(UserInteraction):
            def prompt_up(self):
                print("\n🔑 Touch your security key...", file=sys.stderr, flush=True)

            def request_pin(self, permissions, rd_id):
                from getpass import getpass

                return getpass("Enter FIDO2 PIN: ")

            def request_uv(self, permissions, rd_id):
                print("User verification required on device", file=sys.stderr, flush=True)
                return True

        try:
            origin = f"https://{rp_id}"
            client = Fido2Client(self._device, origin, user_interaction=CliInteraction())

            # Build allow list
            allow_list = None
            if credential_ids:
                allow_list = [
                    PublicKeyCredentialDescriptor(
                        type=PublicKeyCredentialType.PUBLIC_KEY,
                        id=cred_id,
                    )
                    for cred_id in credential_ids
                ]

            # Request options
            options = {
                "rpId": rp_id,
                "challenge": challenge,
                "timeout": self.timeout * 1000,  # ms
                "userVerification": user_verification,
            }
            if allow_list:
                options["allowCredentials"] = allow_list

            # Perform assertion
            result = client.get_assertion(options)
            assertion = result.get_response(0)

            return {
                "authenticatorData": assertion.authenticator_data,
                "clientDataJSON": assertion.client_data,
                "signature": assertion.signature,
                "credentialId": assertion.credential_id,
            }

        except Exception as exc:
            raise FIDO2AuthError(f"FIDO2 authentication failed: {exc}") from exc

    def close(self):
        """Close the FIDO2 device connection."""
        if self._device:
            import contextlib

            with contextlib.suppress(Exception):
                self._device.close()
            self._device = None


def create_fido2_js_bridge(authenticator: FIDO2Authenticator) -> str:
    """Generate JavaScript to inject into the browser to handle WebAuthn calls.

    This replaces navigator.credentials.get() with a version that communicates
    with the local FIDO2 authenticator.

    Returns the JavaScript code as a string.
    """
    return """
    (function() {
        const originalGet = navigator.credentials.get.bind(navigator.credentials);

        navigator.credentials.get = async function(options) {
            if (!options || !options.publicKey) {
                return originalGet(options);
            }

            const pk = options.publicKey;

            // Signal to the Python side that we need FIDO2
            const event = new CustomEvent('openconnect-fido2-request', {
                detail: {
                    challenge: Array.from(new Uint8Array(pk.challenge)),
                    rpId: pk.rpId || window.location.hostname,
                    allowCredentials: (pk.allowCredentials || []).map(c => ({
                        type: c.type,
                        id: Array.from(new Uint8Array(c.id))
                    })),
                    userVerification: pk.userVerification || 'discouraged',
                    timeout: pk.timeout || 30000
                }
            });
            document.dispatchEvent(event);

            // Wait for response from Python side
            return new Promise((resolve, reject) => {
                const handler = function(e) {
                    document.removeEventListener('openconnect-fido2-response', handler);
                    if (e.detail.error) {
                        reject(new DOMException(e.detail.error, 'NotAllowedError'));
                    } else {
                        resolve(e.detail.credential);
                    }
                };
                document.addEventListener('openconnect-fido2-response', handler);

                setTimeout(() => {
                    document.removeEventListener('openconnect-fido2-response', handler);
                    reject(new DOMException('FIDO2 timeout', 'NotAllowedError'));
                }, pk.timeout || 30000);
            });
        };

        console.log('[openconnect-saml] FIDO2 bridge installed');
    })();
    """


def handle_fido2_challenge_headless(
    authenticator: FIDO2Authenticator,
    challenge_data: dict,
) -> dict[str, Any]:
    """Handle a FIDO2 challenge in headless mode.

    Parameters
    ----------
    authenticator : FIDO2Authenticator
        The FIDO2 authenticator instance.
    challenge_data : dict
        The challenge data from the server, containing at least:
        - challenge: base64-encoded challenge
        - rpId: relying party ID

    Returns
    -------
    dict
        The assertion response to send back to the server.
    """
    import base64

    challenge = base64.urlsafe_b64decode(challenge_data["challenge"] + "==")
    rp_id = challenge_data.get("rpId", "")

    credential_ids = None
    if "allowCredentials" in challenge_data:
        credential_ids = [
            base64.urlsafe_b64decode(c["id"] + "==")
            for c in challenge_data["allowCredentials"]
            if c.get("type") == "public-key"
        ]

    user_verification = challenge_data.get("userVerification", "discouraged")

    result = authenticator.authenticate(
        challenge=challenge,
        rp_id=rp_id,
        credential_ids=credential_ids,
        user_verification=user_verification,
    )

    # Encode response for HTTP transport
    return {
        "authenticatorData": base64.urlsafe_b64encode(result["authenticatorData"]).decode(),
        "clientDataJSON": base64.urlsafe_b64encode(result["clientDataJSON"]).decode(),
        "signature": base64.urlsafe_b64encode(result["signature"]).decode(),
        "credentialId": base64.urlsafe_b64encode(result["credentialId"]).decode(),
    }
