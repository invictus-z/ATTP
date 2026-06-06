"""Protocol Node facade — combines authentication / provenance / storage.

Used exclusively by ProtocolNode components (DataPort, ApiPort,
CrossLockCoordinator).  Agent-side tracing is handled by AgentTracer.
"""

from __future__ import annotations

from attp.core.authentication import KeyStore
from attp.core.provenance import ChainManager
from attp.core.storage import SqliteStore


class ProtocolTracer:
    """Facade for Protocol Node: verification, storage, and analysis queries."""

    def __init__(self, db_path: str):
        self._key_store = KeyStore()
        self._chain = ChainManager(key_store=self._key_store)
        self._storage: SqliteStore | None = None
        self._db_path = db_path

    @classmethod
    async def create(cls, db_path: str) -> ProtocolTracer:
        """Async factory: construct instance and initialise storage."""
        tracer = cls(db_path)
        tracer._storage = await SqliteStore.create(db_path)
        return tracer

    # -- key management (delegated to KeyStore) --

    def cache_public_key(self, node_did: str, public_key) -> None:
        """Inject public key into cache (called before verification)."""
        self._key_store.cache_public_key(node_did, public_key)

    @property
    def key_store(self) -> KeyStore:
        """Public read-only access to the internal KeyStore."""
        return self._key_store

    @property
    def chain(self) -> ChainManager:
        """Public read-only access to the internal ChainManager."""
        return self._chain

    @property
    def storage(self) -> SqliteStore:
        """Public read-only access to the internal SqliteStore."""
        return self._storage

    # -- chain verification (delegated to ChainManager) --

    def verify_back_propagation(
        self,
        stored_hop: dict,
        prev_hop: dict,
        session_id: str,
    ) -> tuple[bool, str]:
        return self._chain.verify_back_propagation(
            stored_hop, prev_hop, session_id
        )

    # -- behavior traces --

    async def save_behavior_entry(self, session_id: str, protocol_node_address: str,
                                  sender_did: str, target_did: str = "",
                                  hop_count: list[int] | None = None,
                                  field_type: str = "", content: str = "",
                                  timestamp: float = 0.0,
                                  extra: dict | None = None) -> None:
        await self._storage.save_behavior_entry(
            session_id, protocol_node_address, sender_did, target_did,
            hop_count, field_type, content, timestamp, extra,
        )

    async def recover_behavior_trace(self, session_id: str,
                                     protocol_node_address: str | None = None) -> list:
        return await self._storage.recover_behavior_trace(session_id, protocol_node_address)

    async def recover_traces_since(self, session_id: str, since_id: int) -> tuple[list, int]:
        return await self._storage.recover_traces_since(session_id, since_id)

    async def save_analysis_report(self, report_json: str) -> None:
        await self._storage.save_analysis_report(report_json)

    async def recover_analysis_reports(self, session_id: str) -> list:
        return await self._storage.recover_analysis_reports(session_id)

    # -- analysis session state --

    async def save_analysis_session(self, session_id: str, state: dict) -> None:
        await self._storage.save_analysis_session(session_id, state)

    async def load_analysis_session(self, session_id: str) -> dict | None:
        return await self._storage.load_analysis_session(session_id)

    # -- malicious node reports --

    async def save_malicious_report(self, report) -> None:
        """保存恶意节点报告。

        Args:
            report: MaliciousNodeReport 实例
        """
        for did in report.malicious_dids:
            await self._storage.save_malicious_report(
                session_id=report.session_id,
                malicious_did=did,
                evidence_type=report.evidence_type.value,
                evidence_description=report.evidence_description,
                nonce=report.nonce,
                timestamp=report.timestamp,
                raw_evidence=report.raw_evidence,
            )

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list:
        return await self._storage.query_malicious_nodes(session_id, malicious_did)

    # -- node dossiers --

    async def query_dossier(self, did: str) -> dict | None:
        """查询单个 DID 的恶意节点档案。"""
        return await self._storage.query_dossier(did)

    async def query_all_dossiers(
        self,
        severity_level: str | None = None,
        limit: int = 100,
    ) -> list:
        """查询所有档案，可按 severity_level 筛选。"""
        return await self._storage.query_all_dossiers(severity_level, limit)


# Backward-compatible alias
MessageTracer = ProtocolTracer