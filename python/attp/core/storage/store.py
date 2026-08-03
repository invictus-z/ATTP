"""SqliteStore 外观类 — 委托给底层 Repository（逐跳改版）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from attp.core.sse import EventType, Topic
from attp.core.storage.database import Database
from attp.core.storage.repositories import (
    MaliciousRepository,
    ProtocolSessionRepository,
    TraceRepository,
    VerticalRepository,
)
from attp.core.storage.repositories.horizontal_repo import HorizontalRepository


class SqliteStore:
    """Async SQLite-based trace log storage.

    对外接口与原 SqliteStore 一致（已按逐跳改版调整），内部委托给各 Repository。
    """

    def __init__(self, db_path: str | Path):
        self._db = Database(db_path)
        self._trace = TraceRepository(self._db)
        self._vertical = VerticalRepository(self._db)
        self._malicious = MaliciousRepository(self._db)
        self._session_state = ProtocolSessionRepository(self._db)
        self._horizontal = HorizontalRepository(self._db)
        self._event_broker = None

    def set_event_broker(self, broker) -> None:
        """注入事件总线，用于在写入点发布 trace/malicious 事件。None-safe。"""
        self._event_broker = broker

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
    ) -> int:
        row_id = await self._trace.save_behavior_entry(
            session_id, protocol_node_address, sender_did, target_did,
            hop_count, field_type, content, timestamp, extra,
        )
        if self._event_broker:
            await self._event_broker.publish(
                EventType.TRACE_RECORDED,
                {
                    "session_id": session_id,
                    "trace_id": row_id,
                    "hop_count": hop_count or [0, 0],
                    "field_type": field_type,
                    "sender_did": sender_did,
                    "target_did": target_did,
                    "content": (content or "")[:500],
                    "timestamp": timestamp,
                },
                topic=Topic.TRACE,
            )
        return row_id

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

    # -- vertical hop scores --

    async def save_hop_score(self, score: dict) -> int:
        """保存一条逐跳评分，返回插入行 id。"""
        row_id = await self._vertical.save_hop_score(score)
        if self._event_broker:
            await self._event_broker.publish(
                EventType.HOP_SCORED,
                {
                    "session_id": score.get("session_id", ""),
                    "trace_id": score.get("trace_id", 0),
                    "sender_did": score.get("sender_did", ""),
                    "field_type": score.get("field_type", ""),
                    "score": score.get("score", 0.0),
                    "severity": score.get("severity", "none"),
                    "dimensions": [
                        score.get("dim1", 0.0), score.get("dim2", 0.0),
                        score.get("dim3", 0.0), score.get("dim4", 0.0),
                    ],
                    "breadth": score.get("breadth", 0),
                },
                topic=Topic.ANALYSIS,
            )
        return row_id

    async def query_hop_scores_by_session(self, session_id: str) -> list[dict]:
        return await self._vertical.query_hop_scores_by_session(session_id)

    async def query_hop_scores_by_did(self, did: str, since_id: int = 0) -> list[dict]:
        return await self._vertical.query_hop_scores_by_did(did, since_id)

    async def max_trace_id_for_did(self, did: str) -> int:
        return await self._vertical.max_trace_id_for_did(did)

    async def max_trace_id_for_session(self, session_id: str) -> int:
        return await self._vertical.max_trace_id_for_session(session_id)

    # -- vertical state (intent revisions / hidden state / cursor) --

    async def save_vertical_state(self, session_id: str, state: dict) -> None:
        await self._vertical.save_vertical_state(session_id, state)

    async def load_vertical_state(self, session_id: str) -> dict | None:
        return await self._vertical.load_vertical_state(session_id)

    # -- malicious reports (unified) --

    async def save_malicious_report(self, report: dict) -> int:
        """统一写入 malicious_reports 表。"""
        row_id = await self._malicious.save_malicious_report(report)
        if self._event_broker:
            await self._event_broker.publish(
                EventType.MALICIOUS_DETECTED,
                {
                    "did": report.get("target_did", ""),
                    "severity": report.get("severity", "medium"),
                    "source": report.get("source", ""),
                    "session_id": report.get("session_id", ""),
                    "report_id": row_id,
                    "evidence_type": report.get("evidence_type", ""),
                    "evidence_description": report.get("evidence_description", ""),
                },
                topic=Topic.MALICIOUS,
            )
        return row_id

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
        """保存横向确认报告，返回插入行的 id。"""
        return await self._horizontal.save_horizontal_report(report_json)

    async def recover_horizontal_reports(self, did: str) -> list[dict]:
        return await self._horizontal.recover_horizontal_reports(did)

    async def recover_traces_by_did_since(self, did: str, since_id: int) -> tuple[list[dict], int]:
        return await self._horizontal.recover_traces_by_did_since(did, since_id)

    async def count_traces_by_did_since(self, did: str, since_id: int) -> int:
        """DID 涉及且 id > since_id 的 trace 条数（供「未分析数」）。"""
        return await self._horizontal.count_traces_by_did_since(did, since_id)
