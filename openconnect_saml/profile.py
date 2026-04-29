from pathlib import Path

import structlog
from lxml import etree, objectify

from openconnect_saml.config import HostProfile
from openconnect_saml.xml_utils import make_safe_parser

logger = structlog.get_logger()

ns = {"enc": "http://schemas.xmlsoap.org/encoding/"}


def _get_profiles_from_one_file(path):
    logger.info("Loading profiles from file", path=path.name)

    safe_parser = make_safe_parser()
    try:
        with path.open() as f:
            xml = objectify.parse(f, parser=safe_parser)
    except etree.XMLSyntaxError as exc:
        logger.error("Failed to parse profile XML", path=path.name, error=str(exc))
        return []

    hostentries = xml.xpath("//enc:AnyConnectProfile/enc:ServerList/enc:HostEntry", namespaces=ns)

    profiles = []
    for entry in hostentries:
        try:
            profiles.append(
                HostProfile(
                    name=str(getattr(entry, "HostName", "")),
                    address=str(getattr(entry, "HostAddress", "")),
                    user_group=str(getattr(entry, "UserGroup", "")),
                )
            )
        except (AttributeError, TypeError) as exc:
            logger.warning(
                "Skipping malformed HostEntry in profile",
                path=path.name,
                error=str(exc),
            )

    logger.debug("AnyConnect profiles parsed", path=path.name, profiles=profiles)
    return profiles


def get_profiles(path: Path):
    if path.is_file():
        profile_files = [path]
    elif path.is_dir():
        profile_files = list(path.glob("*.xml"))
    else:
        raise ValueError("No profile file found", path.name)

    profiles = []
    for p in profile_files:
        profiles.extend(_get_profiles_from_one_file(p))
    return profiles
