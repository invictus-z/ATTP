"""Vertical Analysis State Manager — 纵向分析状态管理（逐跳改版）。

封装 ProtocolSession 中 vertical_analysis 状态（发起者 DID / 意图流 / 隐状态 / 打分游标）
的读写。持久化委托给 SqliteStore（vertical_analysis_states 表）。
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
    """纵向分析状态管理 — 意图流 / 隐状态 / 打分游标的持久化封装。"""

    def __init__(self, session_manager: ProtocolSessionManager, tracer: ProtocolTracer):
        self._session_mgr = session_manager
        self._tracer = tracer
        self._restored_sessions: set[str] = set()

    async def _get_or_create(self, session_id: str):
        return await self._session_mgr.get_or_create(session_id)

    async def _save(self, session) -> None:
        await self._session_mgr.save(session)

    async def _persist_state(self, session_id: str) -> None:
        """把当前纵向分析状态写入 SQLite。"""
        session = self._session_mgr.get(session_id)
        if not session:
            return
        state = session.get_analysis_state()
        await self._tracer.save_vertical_state(session_id, {
            "initiator_did": state["initiator_did"],
            "intent_revisions_json": json.dumps(
                state["intent_revisions"], ensure_ascii=False,
            ),
            "hidden_state": state["hidden_state"],
            "last_scored_trace_id": state["last_scored_trace_id"],
        })

    async def restore_state(self, session_id: str) -> None:
        """从 SQLite 恢复纵向分析状态到 Session（每个 session 仅一次）。"""
        if session_id in self._restored_sessions:
            return
        session = await self._get_or_create(session_id)
        if session.get_score_cursor() != 0:
            # 已有内存状态（如本进程内已创建），视为已恢复
            self._restored_sessions.add(session_id)
            return
        saved = await self._tracer.load_vertical_state(session_id)
        if not saved:
            self._restored_sessions.add(session_id)
            return
        if saved.get("initiator_did"):
            session.set_initiator_did(saved["initiator_did"])
        try:
            revisions = json.loads(saved.get("intent_revisions_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            revisions = []
        for rev in revisions:
            session.append_intent_revision(rev)
        if saved.get("hidden_state"):
            session.set_hidden_state(saved["hidden_state"])
        session.advance_score_cursor(saved.get("last_scored_trace_id", 0))
        await self._save(session)
        self._restored_sessions.add(session_id)
        logger.info(
            "Restored vertical state for session={} from SQLite "
            "(initiator={}, revisions={}, cursor={})",
            session_id, session.get_initiator_did(), len(revisions),
            session.get_score_cursor(),
        )

    async def get_state(self, session_id: str) -> dict:
        """获取纵向分析状态。"""
        await self.restore_state(session_id)
        session = await self._get_or_create(session_id)
        return session.get_analysis_state()

    async def set_initiator_did(self, session_id: str, did: str) -> None:
        session = await self._get_or_create(session_id)
        session.set_initiator_did(did)
        await self._save(session)
        await self._persist_state(session_id)

    async def get_initiator_did(self, session_id: str) -> str:
        session = self._session_mgr.get(session_id)
        return session.get_initiator_did() if session else ""

    async def append_intent_revision(self, session_id: str, revision: dict) -> None:
        """追加一条意图增量 Δ 并持久化。"""
        session = await self._get_or_create(session_id)
        session.append_intent_revision(revision)
        await self._save(session)
        await self._persist_state(session_id)

    async def set_hidden_state(self, session_id: str, hidden: str) -> None:
        session = await self._get_or_create(session_id)
        session.set_hidden_state(hidden)
        await self._save(session)
        await self._persist_state(session_id)

    async def advance_score_cursor(self, session_id: str, trace_id: int) -> None:
        """推进打分游标并持久化。"""
        session = await self._get_or_create(session_id)
        session.advance_score_cursor(trace_id)
        await self._save(session)
        await self._persist_state(session_id)
