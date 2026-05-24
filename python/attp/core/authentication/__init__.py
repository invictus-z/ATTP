"""Authentication and key management."""

from .did_resolver import DIDResolver, DIDResolutionResult
from .keys import KeyStore, load_private_key
from .signatures import sign_hash, verify_signature

__all__ = [
    "DIDResolver",
    "DIDResolutionResult",
    "KeyStore",
    "load_private_key",
    "sign_hash",
    "verify_signature",
]