"""Shared XML parsing helpers with XXE protections.

`make_safe_parser` returns an `lxml.objectify` parser configured to refuse
external entity expansion and network lookups, which mitigates billion-laughs
and external-DTD attacks. Used by both the SAML response parser
(`authenticator.py`) and the AnyConnect profile loader (`profile.py`).
"""

from __future__ import annotations

from lxml import objectify


def make_safe_parser(*, recover: bool = False):
    """Create an XML parser with XXE protections.

    Parameters
    ----------
    recover : bool
        If True, the parser tolerates malformed XML (e.g. stray ``<br>`` tags
        in SAML responses, see #171). Defaults to strict.
    """
    return objectify.makeparser(
        resolve_entities=False,
        no_network=True,
        recover=recover,
    )
