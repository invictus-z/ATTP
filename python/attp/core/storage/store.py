"""SqliteStore 外观类 — 委托给底层 Repository。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attp.core.storage.database import Database
from attp.core.storage.repositories import (
    AnalysisRepository,
    MaliciousRepository,
    TraceRepository,
)


class SqliteStore:
    """Async SQLite-based trace log storage.

    对外接口与原 SqliteStore 完全一致，内部委托给各 Repository。
    """

    def __init__(self, db_path: str | Path):
        self._db = Database(db_path)
        self._trace = TraceRepository(self._db)
        self._analysis = AnalysisRepository(self._db)
        self._malicious = MaliciousRepository(self._db)

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
        node_did: str,
        hop_count: list[int],
        field_type: str,
        content: str,
        target: str = "",
        timestamp: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        await self._trace.save_behavior_entry(
            session_id, protocol_node_address, node_did, hop_count,
            field_type, content, target, timestamp, extra,
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

    async def save_analysis_report(self, report_json: str) -> None:
        await self._analysis.save_analysis_report(report_json)

    async def recover_analysis_reports(self, session_id: str) -> list[dict]:
        return await self._analysis.recover_analysis_reports(session_id)

    # -- analysis session state --

    async def save_analysis_session(self, session_id: str, state: dict) -> None:
        await self._analysis.save_analysis_session(session_id, state)

    async def load_analysis_session(self, session_id: str) -> dict | None:
        return await self._analysis.load_analysis_session(session_id)

    # -- malicious node reports --

    async def save_malicious_report(
        self,
        session_id: str,
        malicious_did: str,
        evidence_type: str,
        evidence_description: str = "",
        nonce: str = "",
        timestamp: float = 0.0,
        raw_evidence: dict | None = None,
    ) -> None:
        await self._malicious.save_malicious_report(
            session_id, malicious_did, evidence_type, evidence_description,
            nonce, timestamp, raw_evidence,
        )

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list[dict]:
        return await self._malicious.query_malicious_nodes(session_id, malicious_did)

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
        limit: int = 100,
    ) -> list[dict]:
        return await self._malicious.query_all_dossiers(severity_level, limit)
