"""Vertical Analysis State Manager — 纵向分析状态管理。

封装 ProtocolSession 中 vertical_analysis 状态的读写逻辑。
通过 ProtocolSessionManager 获取/更新 Session 的纵向分析状态。
纵向分析状态的持久化委托给 SqliteStore（vertical_analysis_states 表）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from attp.app.logging import get_logger

if TYPE_CHECKING:
    from attp.core.pn_tracer import ProtocolTracer
    from attp.core.sessions.protocol_node.manager import ProtocolSessionManager

logger = get_logger("VerticalState")


class VerticalAnalysisManager:
    """纵向分析状态管理 — 封装 ProtocolSession 中 vertical_analysis 状态的读写逻辑。"""

    def __init__(self, session_manager: ProtocolSessionManager, tracer: ProtocolTracer):
        self._session_mgr = session_manager
        self._tracer = tracer
        self._restored_sessions: set[str] = set()

    async def _get_or_create(self, session_id: str):
        return await self._session_mgr.get_or_create(session_id)

    async def _save(self, session) -> None:
        await self._session_mgr.save(session)

    async def _persist_state(self, session_id: str) -> None:
        """Write current vertical analysis state to SQLite."""
        session = self._session_mgr.get(session_id)
        if not session:
            return
        state = session.get_analysis_state()
        await self._tracer.save_analysis_session(session_id, {
            "intent_json": json.dumps(state["intent"], ensure_ascii=False) if state["intent"] else None,
            "report_count": state["report_count"],
            "last_trace_id": state["last_trace_id"],
            "batch_index": state["batch_index"],
            "context": state["context"],
        })

    async def restore_state(self, session_id: str) -> None:
        """Restore vertical analysis state from SQLite into Session (only once)."""
        if session_id in self._restored_sessions:
            return
        session = await self._get_or_create(session_id)
        state = session.get_analysis_state()
        if state["last_trace_id"] != 0:
            self._restored_sessions.add(session_id)
            return
        saved = await self._tracer.load_analysis_session(session_id)
        if not saved:
            self._restored_sessions.add(session_id)
            return
        if saved.get("intent_json"):
            session.set_intent(json.loads(saved["intent_json"]))
        session.update_analysis_cursor(
            batch_index=saved.get("batch_index", 0),
            last_trace_id=saved.get("last_trace_id", 0),
            context=saved.get("context") or "",
        )
        for _ in range(saved.get("report_count", 0)):
            session.increment_report_count()
        await self._save(session)
        self._restored_sessions.add(session_id)
        logger.info("Restored vertical analysis state for session={} from SQLite", session_id)

    async def get_state(self, session_id: str) -> dict:
        """获取纵向分析状态。"""
        await self.restore_state(session_id)
        session = await self._get_or_create(session_id)
        return session.get_analysis_state()

    async def increment_report_count(self, session_id: str) -> int:
        """递增纵向报告计数。"""
        session = await self._get_or_create(session_id)
        count = session.increment_report_count()
        await self._save(session)
        await self._persist_state(session_id)
        return count

    async def reset_report_count(self, session_id: str) -> None:
        """重置纵向报告计数。"""
        session = await self._get_or_create(session_id)
        session.reset_report_count()
        await self._save(session)
        await self._persist_state(session_id)

    async def update_cursor(self, session_id: str, batch_index: int, last_trace_id: int, context: str) -> None:
        """更新纵向分析游标。"""
        session = await self._get_or_create(session_id)
        session.update_analysis_cursor(batch_index, last_trace_id, context)
        await self._save(session)
        await self._persist_state(session_id)

    async def set_intent(self, session_id: str, intent: dict) -> None:
        """设置纵向分析的用户意图。"""
        session = await self._get_or_create(session_id)
        session.set_intent(intent)
        await self._save(session)
        await self._persist_state(session_id)

    async def get_intent(self, session_id: str) -> dict | None:
        """获取纵向分析的用户意图。"""
        session = self._session_mgr.get(session_id)
        if not session:
            return None
        return session.get_intent()
