import enum
from pathlib import Path
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


def load():
    path = xdg.BaseDirectory.load_first_config(APP_NAME)
    if not path:
        return Config()
    config_path = Path(path) / "config.toml"
    if not config_path.exists():
        return Config()
    with config_path.open() as config_file:
        try:
            return Config.from_dict(toml.load(config_file))
        except Exception:
            logger.error(
                "Could not load configuration file, ignoring",
                path=config_path,
                exc_info=True,
            )
            return Config()


def save(config):
    path = xdg.BaseDirectory.save_config_path(APP_NAME)
    config_path = Path(path) / "config.toml"
    try:
        config_path.touch()
        with config_path.open("w") as config_file:
            toml.dump(config.as_dict(), config_file)
    except Exception:
        logger.error(
            "Could not save configuration file", path=config_path, exc_info=True
        )


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
    name = attr.ib(converter=str)  # authgroup

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
            AutoFillRule(
                selector="div[data-value=PhoneAppOTP]", action="click"
            ).as_dict(),
            AutoFillRule(selector="a[id=signInAnotherWay]", action="click").as_dict(),
            AutoFillRule(
                selector="input[id=idTxtBx_SAOTCC_OTC]", fill="totp"
            ).as_dict(),
        ]
    }


@attr.s
class Credentials(ConfigNode):
    username = attr.ib()
    _totp_secret = attr.ib(default=None, init=False, repr=False)
    _password = attr.ib(default=None, init=False, repr=False)

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

    @property
    def totp(self):
        if self._totp_secret:
            return pyotp.TOTP(self._totp_secret).now()

        try:
            totpsecret = keyring.get_password(APP_NAME, "totp/" + self.username)
            return pyotp.TOTP(totpsecret).now() if totpsecret else None
        except keyring.errors.KeyringError:
            logger.info("Cannot retrieve saved totp info from keyring.")
            return ""

    @totp.setter
    def totp(self, value):
        self._totp_secret = value

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


@attr.s
class Config(ConfigNode):
    default_profile = attr.ib(default=None, converter=HostProfile.from_dict)
    credentials = attr.ib(default=None, converter=Credentials.from_dict)
    auto_fill_rules = attr.ib(
        factory=get_default_auto_fill_rules,
        converter=lambda rules: {
            n: [AutoFillRule.from_dict(r) for r in rule] for n, rule in rules.items()
        },
    )
    on_disconnect = attr.ib(converter=str, default="")


class DisplayMode(enum.Enum):
    HIDDEN = 0
    SHOWN = 1
