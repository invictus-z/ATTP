"""Agent-side tracer facade — composition of KeyStore + ChainManager.

Agent components (ATTPClient, ATTPServer, MCPToolBridge) only need
hop construction and private-key access.  No database dependency.
"""

from __future__ import annotations

from attp.core.authentication import KeyStore
from attp.core.provenance import ChainManager


class AgentTracer:
    """Lightweight facade for Agent-side tracing operations.

    Combines KeyStore (key caching) and ChainManager (hop construction)
    without any persistent storage.
    """

    def __init__(self) -> None:
        self._key_store = KeyStore()
        self._chain = ChainManager(key_store=self._key_store)

    # -- key management (delegated to KeyStore) --

    def cache_public_key(self, node_did: str, public_key) -> None:
        """Inject a public key into cache (called before verification)."""
        self._key_store.cache_public_key(node_did, public_key)

    def load_private_key(self, key_path: str):
        """Load a private key by file path (cached)."""
        return self._key_store.load_private_key(key_path)

    # -- chain operations (delegated to ChainManager) --

    def append_hop(self, metadata: dict, content: str, node_did: str,
                   target_did: str, private_key_path: str) -> dict:
        return self._chain.append_hop(
            metadata, content, node_did, target_did, private_key_path,
        )

    # -- internal access (for DIDResolver injection) --

    @property
    def key_store(self) -> KeyStore:
        """Public read-only access to the internal KeyStore."""
        return self._key_store