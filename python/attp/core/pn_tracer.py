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
                                  extra: dict | None = None) -> int:
        return await self._storage.save_behavior_entry(
            session_id, protocol_node_address, sender_did, target_did,
            hop_count, field_type, content, timestamp, extra,
        )

    async def recover_behavior_trace(self, session_id: str,
                                     protocol_node_address: str | None = None) -> list:
        return await self._storage.recover_behavior_trace(session_id, protocol_node_address)

    async def recover_traces_since(self, session_id: str, since_id: int) -> tuple[list, int]:
        return await self._storage.recover_traces_since(session_id, since_id)

    # -- vertical hop scores (逐跳评分) --

    async def save_hop_score(self, score: dict) -> int:
        return await self._storage.save_hop_score(score)

    async def query_hop_scores_by_session(self, session_id: str) -> list:
        return await self._storage.query_hop_scores_by_session(session_id)

    async def query_hop_scores_by_did(self, did: str, since_id: int = 0) -> list:
        return await self._storage.query_hop_scores_by_did(did, since_id)

    async def max_trace_id_for_did(self, did: str) -> int:
        return await self._storage.max_trace_id_for_did(did)

    async def max_trace_id_for_session(self, session_id: str) -> int:
        return await self._storage.max_trace_id_for_session(session_id)

    # -- vertical state (意图流 / 隐状态 / 打分游标) --

    async def save_vertical_state(self, session_id: str, state: dict) -> None:
        await self._storage.save_vertical_state(session_id, state)

    async def load_vertical_state(self, session_id: str) -> dict | None:
        return await self._storage.load_vertical_state(session_id)

    # -- malicious reports (unified) --

    async def save_malicious_report(self, report) -> None:
        """保存恶意节点报告（协议审查路径）。

        Args:
            report: MaliciousNodeReport 实例
        """
        for did in report.malicious_dids:
            await self._storage.save_malicious_report({
                "source": "protocol_review",
                "target_did": did,
                "node_type": getattr(report, "node_type", ""),
                "session_id": report.session_id,
                "evidence_type": report.evidence_type.value,
                "severity": "high",
                "taint_score": 0.0,
                "evidence_description": report.evidence_description,
                "nonce": report.nonce,
                "report_id": None,
                "raw_evidence": report.raw_evidence,
                "timestamp": report.timestamp,
            })

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list:
        return await self._storage.query_malicious_nodes(session_id, malicious_did)

    async def query_malicious_reports(
        self,
        session_id: str | None = None,
        target_did: str | None = None,
        source: str | None = None,
    ) -> list:
        """按条件查询恶意报告，支持 source 筛选。"""
        return await self._storage.query_malicious_reports(
            session_id=session_id, target_did=target_did, source=source,
        )

    # -- node dossiers --

    async def query_dossier(self, did: str) -> dict | None:
        """查询单个 DID 的恶意节点档案。"""
        return await self._storage.query_dossier(did)

    async def query_all_dossiers(
        self,
        severity_level: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list:
        """查询所有档案，可按 severity_level / source 筛选。

        返回的每条档案会附带 ``source_breakdown``（各来源违规计数）。
        """
        dossiers = await self._storage.query_all_dossiers(severity_level, source, limit)
        if not dossiers:
            return []
        breakdown = await self._storage.compute_source_breakdown()
        for d in dossiers:
            d["source_breakdown"] = breakdown.get(d["did"], {})
        return dossiers


# Backward-compatible alias
MessageTracer = ProtocolTracer