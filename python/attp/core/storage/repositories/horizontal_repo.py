"""horizontal_analysis_states + horizontal_analysis_reports 仓储（逐跳改版）。

状态表存 per-DID 的累积偏离 F、体积计数、确认游标（last_trace_id）、批次与上下文。
报告表存横轴「确认」报告（confirmed / severity / sessions_reviewed / context_summary）。
"""

from __future__ import annotations

import json
import time as _time

from attp.app.logging import get_logger
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class HorizontalRepository(BaseRepository):
    """horizontal_analysis_states + horizontal_analysis_reports CRUD。"""

    # ------------------------------------------------------------------
    # 状态 horizontal_analysis_states
    # ------------------------------------------------------------------

    async def save_horizontal_state(self, did: str, state: dict) -> None:
        """INSERT OR REPLACE 横向分析状态（F / volume / cursor / batch / context）。"""
        await self._db.execute(
            """INSERT OR REPLACE INTO horizontal_analysis_states
               (did, node_type, f_value, volume, last_trace_id,
                batch_index, context, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                did,
                state.get("node_type", "agent"),
                state.get("f_value", 0.0),
                state.get("volume", 0),
                state.get("last_trace_id", 0),
                state.get("batch_index", 0),
                state.get("context", ""),
                _time.time(),
            ),
        )

    async def load_horizontal_state(self, did: str) -> dict | None:
        return await self._db.execute_fetchone(
            "SELECT * FROM horizontal_analysis_states WHERE did = ?",
            (did,),
        )

    # ------------------------------------------------------------------
    # 报告 horizontal_analysis_reports
    # ------------------------------------------------------------------

    async def save_horizontal_report(self, report_json: str) -> int:
        """保存横向确认报告，返回插入行 id。"""
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
            "Saved horizontal report: did={}, batch={}, confirmed={}, id={}",
            report.get("did"), report.get("batch_index"),
            report.get("confirmed"), row_id,
        )
        return row_id

    async def recover_horizontal_reports(self, did: str) -> list[dict]:
        """查询 DID 的全部横向确认报告。"""
        return await self._db.execute_fetch(
            """SELECT * FROM horizontal_analysis_reports
               WHERE did = ?
               ORDER BY batch_index""",
            (did,),
        )

    # ------------------------------------------------------------------
    # 跨会话 trace 取数（供确认画像）
    # ------------------------------------------------------------------

    async def recover_traces_by_did_since(
        self, did: str, since_id: int,
    ) -> tuple[list[dict], int]:
        """恢复指定 DID 在所有会话中、since_id 之后的全部 trace。

        包含该 DID 作为 sender(node_did) 和 receiver(target) 的记录，
        供横轴确认时构建跨会话画像。
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
        """统计 DID 涉及的会话数量。"""
        row = await self._db.execute_fetchone(
            """SELECT COUNT(DISTINCT session_id) as cnt FROM behavior_traces
               WHERE (node_did = ? OR target = ?) AND id > ?""",
            (did, did, since_id),
        )
        return row["cnt"] if row else 0

    async def count_traces_by_did_since(self, did: str, since_id: int) -> int:
        """统计 DID 涉及（sender 或 receiver）且 id > since_id 的 trace 条数。

        供「未分析数」：since_id 取确认游标 last_trace_id（最后一次分析位置），
        结果即该节点在游标之后、尚未汇入确认报告的全部跳数。
        """
        row = await self._db.execute_fetchone(
            """SELECT COUNT(*) as cnt FROM behavior_traces
               WHERE (node_did = ? OR target = ?) AND id > ?""",
            (did, did, since_id),
        )
        return row["cnt"] if row else 0
