"""horizontal_analysis_states + horizontal_analysis_reports 仓储。"""

from __future__ import annotations

import json
import time as _time

from attp.app.logging import get_logger
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class HorizontalRepository(BaseRepository):
    """horizontal_analysis_states + horizontal_analysis_reports CRUD。"""

    async def save_horizontal_state(self, did: str, state: dict) -> None:
        """INSERT OR REPLACE 横向分析状态。"""
        await self._db.execute(
            """INSERT OR REPLACE INTO horizontal_analysis_states
               (did, node_type, accumulated_count, last_trace_id,
                batch_index, context, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                did,
                state.get("node_type", "agent"),
                state.get("accumulated_count", 0),
                state.get("last_trace_id", 0),
                state.get("batch_index", 0),
                state.get("context", ""),
                _time.time(),
            ),
        )

    async def load_horizontal_state(self, did: str) -> dict | None:
        """加载横向分析状态。"""
        return await self._db.execute_fetchone(
            "SELECT * FROM horizontal_analysis_states WHERE did = ?",
            (did,),
        )

    async def increment_accumulated_count(self, did: str) -> int:
        """原子递增累积计数并返回新值。"""
        # Load current state
        row = await self.load_horizontal_state(did)
        if row is None:
            await self.save_horizontal_state(did, {"accumulated_count": 1})
            return 1
        new_count = row.get("accumulated_count", 0) + 1
        await self._db.execute(
            """UPDATE horizontal_analysis_states
               SET accumulated_count = ?, updated_at = ?
               WHERE did = ?""",
            (new_count, _time.time(), did),
        )
        return new_count

    async def reset_accumulated_count(self, did: str) -> None:
        """重置累积计数。"""
        await self._db.execute(
            """UPDATE horizontal_analysis_states
               SET accumulated_count = 0, updated_at = ?
               WHERE did = ?""",
            (_time.time(), did),
        )

    async def save_horizontal_report(self, report_json: str) -> int:
        """保存横向分析报告，返回插入行的 id。"""
        report = json.loads(report_json)
        row_id = await self._db.execute_insert(
            """INSERT INTO horizontal_analysis_reports
               (did, node_type, batch_index, report_json,
                from_trace_id, to_trace_id, sessions_scanned, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.get("did", ""),
                report.get("node_type", ""),
                report.get("batch_index", 0),
                report_json,
                report.get("from_trace_id", 0),
                report.get("to_trace_id", 0),
                report.get("sessions_scanned", 0),
                report.get("timestamp", 0.0),
            ),
        )
        logger.info(
            "Saved horizontal report: did={}, batch={}, id={}",
            report.get("did"), report.get("batch_index"), row_id,
        )
        return row_id

    async def recover_horizontal_reports(self, did: str) -> list[dict]:
        """查询DID的全部横向分析报告。"""
        return await self._db.execute_fetch(
            """SELECT * FROM horizontal_analysis_reports
               WHERE did = ?
               ORDER BY batch_index""",
            (did,),
        )

    async def recover_traces_by_did_since(
        self, did: str, since_id: int,
    ) -> tuple[list[dict], int]:
        """恢复指定DID在所有Session中、since_id之后的全部trace。

        包含该DID作为sender(node_did)和receiver(target)的记录。
        """
        result = await self._db.execute_fetch(
            """SELECT * FROM behavior_traces
               WHERE (node_did = ? OR target = ?) AND id > ?
               ORDER BY id""",
            (did, did, since_id),
        )
        for row in result:
            row["hop_count"] = [row.pop("hop_count_a2a", 0), row.pop("hop_count_intra", 0)]
            row["sender_did"] = row.get("node_did", "")
            row["target_did"] = row.get("target", "")
        max_id = result[-1]["id"] if result else since_id
        return result, max_id

    async def count_sessions_for_did(self, did: str, since_id: int = 0) -> int:
        """统计DID涉及的Session数量。"""
        row = await self._db.execute_fetchone(
            """SELECT COUNT(DISTINCT session_id) as cnt FROM behavior_traces
               WHERE (node_did = ? OR target = ?) AND id > ?""",
            (did, did, since_id),
        )
        return row["cnt"] if row else 0
