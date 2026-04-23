"""Facade 门面模式：组合 authentication / provenance / storage 子模块，
对老代码提供与原始 MessageTracer 完全一致的公共 API。"""

from attp_channel.protocol.authentication import KeyStore
from attp_channel.protocol.provenance import ChainManager
from attp_channel.protocol.storage import SqliteStore


class MessageTracer:
    """Facade that composes sub-modules and exposes the original public API.

    Every public method signature is identical to the old monolithic MessageTracer,
    so callers (server.py, client.py, trace.py) need zero changes.
    """

    def __init__(self, db_path: str = "attp_traces.db"):
        self._key_store = KeyStore()
        self._storage = SqliteStore(db_path=db_path)
        self._chain = ChainManager(key_store=self._key_store, storage=self._storage)

    # -- key management (delegated to KeyStore) --

    def cache_public_key(self, node_did: str, public_key) -> None:
        """注入公钥到缓存（由异步调用方在 validate_chain 前调用）。"""
        self._key_store.cache_public_key(node_did, public_key)

    @property
    def _pub_key_cache(self) -> dict:
        """Backward-compatible access to the internal cache dict."""
        return self._key_store.cache_dict

    # -- chain operations (delegated to ChainManager) --

    def append_hop(self, metadata: dict, content: str, node_did: str,
                   target_did: str, private_key_path: str,
                   save_to_db: bool = True) -> dict:
        return self._chain.append_hop(
            metadata, content, node_did, target_did,
            private_key_path, save_to_db,
        )

    def validate_chain(self, metadata: dict, content: str) -> bool:
        return self._chain.validate_chain(metadata, content)

    def get_origin_did(self, metadata: dict) -> str | None:
        return self._chain.get_origin_did(metadata)

    # -- storage (delegated to SqliteStore) --

    def save_log_to_db(self, log_entry: dict) -> bool:
        return self._storage.save_log_to_db(log_entry)

    def recover_trace(self, session_id: str) -> list:
        return self._storage.recover_trace(session_id)
