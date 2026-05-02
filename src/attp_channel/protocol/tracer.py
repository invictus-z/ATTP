"""Facade 门面模式：组合 authentication / provenance / storage 子模块。"""

from __future__ import annotations

from attp_channel.protocol.authentication import KeyStore
from attp_channel.protocol.provenance import ChainManager
from attp_channel.protocol.storage import SqliteStore
from attp_channel.sessions.node_message import NodeMessage


class MessageTracer:
    """Facade that composes sub-modules and exposes a unified public API."""

    def __init__(self, db_path: str):
        self._key_store = KeyStore()
        self._chain = ChainManager(key_store=self._key_store)
        self._storage: SqliteStore | None = None
        self._db_path = db_path

    @classmethod
    async def create(cls, db_path: str) -> MessageTracer:
        """Async factory: construct instance and initialise storage."""
        tracer = cls(db_path)
        tracer._storage = await SqliteStore.create(db_path)
        return tracer

    # -- key management (delegated to KeyStore) --

    def cache_public_key(self, node_did: str, public_key) -> None:
        """注入公钥到缓存（由异步调用方在 validate 前调用）。"""
        self._key_store.cache_public_key(node_did, public_key)

    @property
    def _pub_key_cache(self) -> dict:
        """Backward-compatible access to the internal cache dict."""
        return self._key_store.cache_dict

    # -- chain operations (delegated to ChainManager) --

    def append_hop(self, metadata: dict, content: str, node_did: str,
                   target_did: str, private_key_path: str) -> dict:
        return self._chain.append_hop(
            metadata, content, node_did, target_did,
            private_key_path,
        )

    def verify_back_propagation(
        self,
        stored_hop: dict,
        prev_hop: dict,
        session_id: str,
        origin_did: str,
    ) -> tuple[bool, str]:
        return self._chain.verify_back_propagation(
            stored_hop, prev_hop, session_id, origin_did
        )

    # -- behavior traces (a/b/c/d) --

    async def save_behavior_entry(self, session_id: str, origin_did: str,
                                  node_did: str, hop_count: int,
                                  field_type: str, content: str,
                                  target: str = "", timestamp: float = 0.0,
                                  extra: dict | None = None) -> None:
        await self._storage.save_behavior_entry(
            session_id, origin_did, node_did, hop_count,
            field_type, content, target, timestamp, extra,
        )

    async def save_node_message(self, node_message: NodeMessage) -> None:
        await self._storage.save_node_message(node_message)

    async def recover_behavior_trace(self, session_id: str,
                                     origin_did: str | None = None) -> list:
        return await self._storage.recover_behavior_trace(session_id, origin_did)

    async def recover_traces_since(self, session_id: str, since_id: int) -> tuple[list, int]:
        return await self._storage.recover_traces_since(session_id, since_id)

    async def save_analysis_report(self, report_json: str) -> None:
        await self._storage.save_analysis_report(report_json)

    async def recover_analysis_reports(self, session_id: str) -> list:
        return await self._storage.recover_analysis_reports(session_id)
