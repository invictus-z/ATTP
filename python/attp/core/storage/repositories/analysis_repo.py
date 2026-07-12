"""analysis_reports 和 analysis_sessions 的读写。"""

from __future__ import annotations

import json
import time as _time

from attp.app.logging import get_logger
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class AnalysisRepository(BaseRepository):
    """analysis_reports + analysis_sessions CRUD。"""

    async def save_analysis_report(self, report_json: str) -> int:
        """保存纵向分析报告，返回插入行的 id。"""
        report = json.loads(report_json)
        row_id = await self._db.execute_insert(
            """INSERT INTO vertical_analysis_reports
               (session_id, batch_index, report_json,
                from_trace_id, to_trace_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                report.get("session_id", ""),
                report.get("batch_index", 0),
                report_json,
                report.get("from_trace_id", 0),
                report.get("to_trace_id", 0),
                report.get("timestamp", 0.0),
            ),
        )
        logger.info(
            "Saved analysis report: session={}, batch={}, id={}",
            report.get("session_id"), report.get("batch_index"), row_id,
        )
        return row_id

    async def recover_analysis_reports(self, session_id: str) -> list[dict]:
        return await self._db.execute_fetch(
            """SELECT * FROM vertical_analysis_reports
               WHERE session_id = ?
               ORDER BY batch_index""",
            (session_id,),
        )

    async def save_analysis_session(self, session_id: str, state: dict) -> None:
        await self._db.execute(
            """INSERT OR REPLACE INTO vertical_analysis_states
               (session_id, intent_json, pending_count, last_trace_id,
                batch_index, context, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                state.get("intent_json"),
                state.get("pending_count", 0),
                state.get("last_trace_id", 0),
                state.get("batch_index", 0),
                state.get("context", ""),
                _time.time(),
            ),
        )

    async def load_analysis_session(self, session_id: str) -> dict | None:
        return await self._db.execute_fetchone(
            "SELECT * FROM vertical_analysis_states WHERE session_id = ?",
            (session_id,),
        )
