"""SqliteStore 外观类 — 委托给底层 Repository。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attp.core.storage.database import Database
from attp.core.storage.repositories import (
    AnalysisRepository,
    MaliciousRepository,
    ProtocolSessionRepository,
    TraceRepository,
)
from attp.core.storage.repositories.horizontal_repo import HorizontalRepository


class SqliteStore:
    """Async SQLite-based trace log storage.

    对外接口与原 SqliteStore 完全一致，内部委托给各 Repository。
    """

    def __init__(self, db_path: str | Path):
        self._db = Database(db_path)
        self._trace = TraceRepository(self._db)
        self._analysis = AnalysisRepository(self._db)
        self._malicious = MaliciousRepository(self._db)
        self._session_state = ProtocolSessionRepository(self._db)
        self._horizontal = HorizontalRepository(self._db)

    @classmethod
    async def create(cls, db_path: str | Path) -> SqliteStore:
        """Async factory: construct instance and initialise tables."""
        store = cls(db_path)
        await store._db.initialize()
        return store

    # -- behavior_traces --

    async def save_behavior_entry(
        self,
        session_id: str,
        protocol_node_address: str,
        sender_did: str,
        target_did: str = "",
        hop_count: list[int] | None = None,
        field_type: str = "",
        content: str = "",
        timestamp: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await self._trace.save_behavior_entry(
            session_id, protocol_node_address, sender_did, target_did,
            hop_count, field_type, content, timestamp, extra,
        )

    async def recover_behavior_trace(
        self,
        session_id: str,
        protocol_node_address: str | None = None,
    ) -> list[dict]:
        return await self._trace.recover_behavior_trace(session_id, protocol_node_address)

    async def recover_traces_since(
        self,
        session_id: str,
        since_id: int,
    ) -> tuple[list[dict], int]:
        return await self._trace.recover_traces_since(session_id, since_id)

    # -- analysis_reports --

    async def save_analysis_report(self, report_json: str) -> int:
        """保存纵向分析报告，返回插入行的 id。"""
        return await self._analysis.save_analysis_report(report_json)

    async def recover_analysis_reports(self, session_id: str) -> list[dict]:
        return await self._analysis.recover_analysis_reports(session_id)

    # -- analysis session state --

    async def save_analysis_session(self, session_id: str, state: dict) -> None:
        await self._analysis.save_analysis_session(session_id, state)

    async def load_analysis_session(self, session_id: str) -> dict | None:
        return await self._analysis.load_analysis_session(session_id)

    # -- malicious reports (unified) --

    async def save_malicious_report(self, report: dict) -> int:
        """统一写入 malicious_reports 表。

        Args:
            report: 包含 source, target_did, node_type, session_id,
                    evidence_type, severity, taint_score,
                    evidence_description, nonce, report_id,
                    raw_evidence, timestamp 的字典。

        Returns:
            插入行的 id。
        """
        return await self._malicious.save_malicious_report(report)

    async def query_malicious_reports(
        self,
        session_id: str | None = None,
        target_did: str | None = None,
        source: str | None = None,
    ) -> list[dict]:
        """按条件查询恶意报告，支持 source 筛选。"""
        return await self._malicious.query_malicious_reports(
            session_id=session_id, target_did=target_did, source=source,
        )

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list[dict]:
        """兼容旧接口。"""
        return await self._malicious.query_malicious_nodes(
            session_id=session_id, malicious_did=malicious_did,
        )

    # -- node dossiers --

    async def upsert_dossier(
        self,
        malicious_did: str,
        evidence_type: str,
        session_id: str,
        description: str,
    ) -> None:
        await self._malicious.upsert_dossier(malicious_did, evidence_type, session_id, description)

    async def query_dossier(self, did: str) -> dict | None:
        return await self._malicious.query_dossier(did)

    async def query_all_dossiers(
        self,
        severity_level: str | None = None,
        source: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return await self._malicious.query_all_dossiers(severity_level, source, limit)

    async def compute_source_breakdown(self) -> dict[str, dict[str, int]]:
        """返回 {did: {source: count}} 映射。"""
        return await self._malicious.compute_source_breakdown()

    # -- protocol session state --

    async def save_verification_state(self, session_id: str, state: dict) -> None:
        await self._session_state.save_verification_state(session_id, state)

    async def load_verification_state(self, session_id: str) -> dict | None:
        return await self._session_state.load_verification_state(session_id)

    # -- horizontal analysis --

    async def save_horizontal_state(self, did: str, state: dict) -> None:
        await self._horizontal.save_horizontal_state(did, state)

    async def load_horizontal_state(self, did: str) -> dict | None:
        return await self._horizontal.load_horizontal_state(did)

    async def save_horizontal_report(self, report_json: str) -> int:
        """保存横向分析报告，返回插入行的 id。"""
        return await self._horizontal.save_horizontal_report(report_json)

    async def recover_horizontal_reports(self, did: str) -> list[dict]:
        return await self._horizontal.recover_horizontal_reports(did)

    async def recover_traces_by_did_since(self, did: str, since_id: int) -> tuple[list[dict], int]:
        return await self._horizontal.recover_traces_by_did_since(did, since_id)
