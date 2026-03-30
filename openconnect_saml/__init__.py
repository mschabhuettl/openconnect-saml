import importlib.metadata

_metadata = importlib.metadata.metadata("openconnect-saml")

__version__ = _metadata["Version"]
__description__ = _metadata["Summary"]
