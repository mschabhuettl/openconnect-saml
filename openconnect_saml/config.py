from __future__ import annotations

import binascii
import enum
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import attr
import keyring
import keyring.errors
import pyotp
import structlog
import toml
import xdg.BaseDirectory

logger = structlog.get_logger()

APP_NAME = "openconnect-saml"
# Environment variable to override the default XDG config location. CLI flag
# ``--config FILE`` writes here so all subsequent ``config.load`` / ``config.save``
# calls honor the override without threading an explicit path through every call.
CONFIG_ENV_VAR = "OPENCONNECT_SAML_CONFIG"


def _override_path() -> Path | None:
    override = os.environ.get(CONFIG_ENV_VAR)
    return Path(override) if override else None


def _read_path() -> Path | None:
    """Return the path ``load`` will read from, or ``None`` if no config exists."""
    if (override := _override_path()) is not None:
        return override
    base = xdg.BaseDirectory.load_first_config(APP_NAME)
    if not base:
        return None
    return Path(base) / "config.toml"


def _write_path() -> Path:
    """Return the path ``save`` will write to, creating the parent dir if needed."""
    if (override := _override_path()) is not None:
        override.parent.mkdir(parents=True, exist_ok=True)
        return override
    base = xdg.BaseDirectory.save_config_path(APP_NAME)
    return Path(base) / "config.toml"


def config_path() -> Path:
    """Path the CLI / docs should display.

    Resolves to: ``$OPENCONNECT_SAML_CONFIG`` if set, otherwise the existing
    XDG config file if present, otherwise the path where ``save`` would create
    one (without actually creating it).
    """
    if (override := _override_path()) is not None:
        return override
    base = xdg.BaseDirectory.load_first_config(APP_NAME)
    if base:
        return Path(base) / "config.toml"
    fallback = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(fallback) / APP_NAME / "config.toml"


def load():
    path = _read_path()
    if path is None or not path.exists():
        return Config()
    with path.open() as config_file:
        try:
            return Config.from_dict(toml.load(config_file))
        except Exception:
            logger.error(
                "Could not load configuration file, ignoring",
                path=path,
                exc_info=True,
            )
            return Config()


def save(config):
    path = _write_path()
    try:
        path.touch(mode=0o600)
        path.chmod(0o600)
        with path.open("w") as config_file:
            toml.dump(config.as_dict(), config_file)
    except Exception:
        logger.error("Could not save configuration file", path=path, exc_info=True)


@attr.s
class ConfigNode:
    @classmethod
    def from_dict(cls, d):
        if d is None:
            return None
        return cls(**d)

    def as_dict(self):
        return attr.asdict(self, filter=lambda a, v: a.init)


@attr.s
class HostProfile(ConfigNode):
    address = attr.ib(converter=str)
    user_group = attr.ib(converter=str)
    name = attr.ib(converter=str)

    @property
    def vpn_url(self):
        parts = urlparse(self.address)
        group = self.user_group or parts.path
        if parts.path == self.address and not self.user_group:
            group = ""
        return urlunparse(
            (parts.scheme or "https", parts.netloc or self.address, group, "", "", "")
        )


@attr.s
class AutoFillRule(ConfigNode):
    selector = attr.ib()
    fill = attr.ib(default=None)
    action = attr.ib(default=None)


def get_default_auto_fill_rules():
    return {
        "https://*": [
            AutoFillRule(selector="div[id=passwordError]", action="stop").as_dict(),
            AutoFillRule(selector="input[type=email]", fill="username").as_dict(),
            AutoFillRule(selector="input[name=passwd]", fill="password").as_dict(),
            AutoFillRule(
                selector="input[data-report-event=Signin_Submit]", action="click"
            ).as_dict(),
            AutoFillRule(selector="div[data-value=PhoneAppOTP]", action="click").as_dict(),
            AutoFillRule(selector="a[id=signInAnotherWay]", action="click").as_dict(),
            AutoFillRule(selector="input[id=idTxtBx_SAOTCC_OTC]", fill="totp").as_dict(),
            AutoFillRule(selector="div[data-value=PhoneAppNotification]", action="click").as_dict(),
            AutoFillRule(selector="input[id=KmsiCheckboxField]", action="click").as_dict(),
            AutoFillRule(selector="input[id=idSIButton9]", action="click").as_dict(),
        ]
    }


@attr.s
class TwoFAuthConfig(ConfigNode):
    """Configuration for a remote 2FAuth TOTP provider."""

    url = attr.ib(default="")
    token = attr.ib(default="", repr=False)
    account_id = attr.ib(default=0, converter=int)


@attr.s
class BitwardenConfig(ConfigNode):
    """Configuration for the Bitwarden TOTP provider."""

    item_id = attr.ib(default="")


@attr.s
class OnePasswordConfig(ConfigNode):
    """Configuration for the 1Password TOTP provider."""

    item = attr.ib(default="")
    vault = attr.ib(default="")
    account = attr.ib(default="")


@attr.s
class PassConfig(ConfigNode):
    """Configuration for the pass/password-store TOTP provider."""

    entry = attr.ib(default="")


@attr.s
class KillSwitchSettings(ConfigNode):
    """Persisted kill-switch settings (loaded via ``[kill_switch]`` section)."""

    enabled = attr.ib(default=False, converter=bool)
    allow_lan = attr.ib(default=False, converter=bool)
    ipv6 = attr.ib(default=True, converter=bool)

    @staticmethod
    def _convert_dns_servers(val):
        if val is None:
            return []
        return [str(v) for v in val]

    dns_servers = attr.ib(factory=list, converter=_convert_dns_servers)


@attr.s
class Credentials(ConfigNode):
    username = attr.ib()
    totp_source = attr.ib(default="local")  # local, 2fauth, bitwarden, 1password, pass
    _totp_secret = attr.ib(default=None, init=False, repr=False)
    _password = attr.ib(default=None, init=False, repr=False)
    _totp_provider = attr.ib(default=None, init=False, repr=False)

    @property
    def password(self):
        if self._password:
            return self._password

        try:
            return keyring.get_password(APP_NAME, self.username)
        except keyring.errors.KeyringError:
            logger.info("Cannot retrieve saved password from keyring.")
            return ""

    @password.setter
    def password(self, value):
        self._password = value

    @password.deleter
    def password(self):
        try:
            keyring.delete_password(APP_NAME, self.username)
        except keyring.errors.KeyringError:
            logger.info("Cannot delete saved password from keyring.")

    @property
    def totp(self):
        if self._totp_provider is not None:
            return self._totp_provider.get_totp()

        if self._totp_secret:
            try:
                return pyotp.TOTP(self._totp_secret).now()
            except (binascii.Error, ValueError) as exc:
                logger.warning(
                    "Corrupt TOTP secret in memory (#143), ignoring. "
                    "You will be prompted to re-enter it.",
                    error=str(exc),
                )
                self._totp_secret = None
                return None
            except Exception:
                logger.warning("Invalid TOTP secret in memory, ignoring")
                return None

        try:
            totpsecret = keyring.get_password(APP_NAME, "totp/" + self.username)
            if totpsecret:
                try:
                    return pyotp.TOTP(totpsecret).now()
                except (binascii.Error, ValueError) as exc:
                    logger.warning(
                        "Corrupt TOTP secret in keyring (#143), ignoring. "
                        "Use --reset-credentials to clear it or re-enter when prompted.",
                        error=str(exc),
                    )
                    return None
                except Exception:
                    logger.warning(
                        "Invalid TOTP secret in keyring, ignoring. "
                        "Use --reset-credentials to clear it."
                    )
                    return None
            return None
        except keyring.errors.KeyringError:
            logger.info("Cannot retrieve saved totp info from keyring.")
            return ""

    @totp.setter
    def totp(self, value):
        self._totp_secret = value

    @totp.deleter
    def totp(self):
        try:
            keyring.delete_password(APP_NAME, "totp/" + self.username)
        except keyring.errors.KeyringError:
            logger.info("Cannot delete saved totp secret from keyring.")

    def set_totp_provider(self, provider):
        """Attach a custom :class:`TotpProvider` (e.g. 2FAuth, 1Password, pass)."""
        self._totp_provider = provider

    def save(self):
        if self._password:
            try:
                keyring.set_password(APP_NAME, self.username, self._password)
            except keyring.errors.KeyringError:
                logger.info("Cannot save password to keyring.")

        if self._totp_secret:
            try:
                keyring.set_password(APP_NAME, "totp/" + self.username, self._totp_secret)
            except keyring.errors.KeyringError:
                logger.info("Cannot save totp secret to keyring.")


def _node_converter(cls: type) -> Callable[[Any], Any]:
    """Return an attrs converter that turns ``None`` / dict / instance into ``cls``."""

    def _convert(val: Any) -> Any:
        if val is None:
            return None
        if isinstance(val, cls):
            return val
        return cls.from_dict(val)

    _convert.__name__ = f"_convert_{cls.__name__.lower()}"
    return _convert


_convert_twofauth = _node_converter(TwoFAuthConfig)
_convert_bitwarden = _node_converter(BitwardenConfig)
_convert_onepassword = _node_converter(OnePasswordConfig)
_convert_pass = _node_converter(PassConfig)
_convert_killswitch = _node_converter(KillSwitchSettings)


def _convert_str_list(val):
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    return val


# Aliases used in TOML to map cleanly onto Python identifiers (digits + reserved
# words can't appear at the start of a variable name).
_TOML_KEY_ALIASES: tuple[tuple[str, str], ...] = (
    ("2fauth", "twofauth"),
    ("1password", "onepassword"),
    ("pass", "pass_"),
)


def _rename_toml_to_py(d: dict) -> dict:
    """Translate TOML-style section names to attrs field names."""
    d = dict(d)
    for toml_key, py_key in _TOML_KEY_ALIASES:
        if toml_key in d:
            d[py_key] = d.pop(toml_key)
    return d


def _rename_py_to_toml(d: dict) -> dict:
    """Translate attrs field names back to TOML-style section names."""
    for toml_key, py_key in _TOML_KEY_ALIASES:
        if py_key in d:
            val = d.pop(py_key)
            if val is not None:
                d[toml_key] = val
    return d


@attr.s
class ProfileConfig(ConfigNode):
    """A named VPN profile with server, credentials, and optional settings."""

    server = attr.ib(converter=str)
    user_group = attr.ib(converter=str, default="")
    name = attr.ib(converter=str, default="")
    credentials = attr.ib(default=None, converter=Credentials.from_dict)
    twofauth = attr.ib(default=None, converter=_convert_twofauth)
    bitwarden = attr.ib(default=None, converter=_convert_bitwarden)
    onepassword = attr.ib(default=None, converter=_convert_onepassword)
    pass_ = attr.ib(default=None, converter=_convert_pass)
    routes = attr.ib(factory=list, converter=_convert_str_list)
    no_routes = attr.ib(factory=list, converter=_convert_str_list)

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return None
        return cls(**_rename_toml_to_py(d))

    def as_dict(self):
        d = attr.asdict(self, filter=lambda a, v: a.init)
        return _rename_py_to_toml(d)

    def to_host_profile(self):
        """Convert to a HostProfile for authentication."""
        return HostProfile(self.server, self.user_group, self.name)


def _convert_profiles(val):
    if val is None:
        return {}
    if isinstance(val, dict):
        result = {}
        for k, v in val.items():
            if isinstance(v, ProfileConfig):
                result[k] = v
            elif isinstance(v, dict):
                result[k] = ProfileConfig.from_dict(v)
            else:
                result[k] = v
        return result
    return val


@attr.s
class Config(ConfigNode):
    default_profile = attr.ib(default=None, converter=HostProfile.from_dict)
    credentials = attr.ib(default=None, converter=Credentials.from_dict)
    twofauth = attr.ib(default=None, converter=_convert_twofauth)
    bitwarden = attr.ib(default=None, converter=_convert_bitwarden)
    onepassword = attr.ib(default=None, converter=_convert_onepassword)
    pass_ = attr.ib(default=None, converter=_convert_pass)
    profiles = attr.ib(factory=dict, converter=_convert_profiles)
    active_profile = attr.ib(default=None)
    notifications = attr.ib(default=False, converter=bool)
    connection_history = attr.ib(default=True, converter=bool)
    kill_switch = attr.ib(default=None, converter=_convert_killswitch)

    @classmethod
    def from_dict(cls, d):
        if d is None:
            return None
        return cls(**_rename_toml_to_py(d))

    def as_dict(self):
        d = attr.asdict(self, filter=lambda a, v: a.init)
        return _rename_py_to_toml(d)

    def get_profile(self, name):
        """Get a named profile, or None."""
        return self.profiles.get(name)

    def add_profile(self, name, profile):
        """Add or update a named profile."""
        if isinstance(profile, dict):
            profile = ProfileConfig.from_dict(profile)
        self.profiles[name] = profile

    def remove_profile(self, name):
        """Remove a named profile. Returns True if it existed."""
        if name in self.profiles:
            del self.profiles[name]
            return True
        return False

    def list_profiles(self):
        """Return list of (name, ProfileConfig) tuples."""
        return list(self.profiles.items())

    auto_fill_rules = attr.ib(
        factory=get_default_auto_fill_rules,
        converter=lambda rules: {
            n: [AutoFillRule.from_dict(r) for r in rule] for n, rule in rules.items()
        },
    )
    on_disconnect = attr.ib(converter=str, default="")
    on_connect = attr.ib(converter=str, default="")
    timeout = attr.ib(converter=lambda v: int(v) if v is not None else 30, default=30)
    window_width = attr.ib(converter=lambda v: int(v) if v is not None else 800, default=800)
    window_height = attr.ib(converter=lambda v: int(v) if v is not None else 600, default=600)


class DisplayMode(enum.Enum):
    HIDDEN = 0
    SHOWN = 1


# Supported auto-fill action types (including FIDO2)
AUTOFILL_ACTIONS = ("click", "stop", "fido2")

# Supported TOTP source names (used for CLI validation and setup wizard)
TOTP_SOURCES = ("local", "2fauth", "bitwarden", "1password", "pass")
