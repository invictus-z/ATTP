"""vertical_hop_scores + vertical_analysis_states 仓储（逐跳改版）。"""

from __future__ import annotations

import json
import time as _time

from attp.app.logging import get_logger
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class VerticalRepository(BaseRepository):
    """vertical_hop_scores（逐跳评分）+ vertical_analysis_states（意图流/隐状态/游标）CRUD。"""

    # ------------------------------------------------------------------
    # 逐跳评分 vertical_hop_scores
    # ------------------------------------------------------------------

    async def save_hop_score(self, score: dict) -> int:
        """保存一条逐跳评分，返回插入行 id。

        score 字段：trace_id, session_id, sender_did, field_type, hop_count[a2a,intra],
        score, dim1..dim4, breadth, severity, deviation_type, evidence_refs(list[dict]),
        hidden_state, timestamp。
        """
        hc = score.get("hop_count") or [0, 0]
        evidence_refs = score.get("evidence_refs") or []
        row_id = await self._db.execute_insert(
            """INSERT INTO vertical_hop_scores
               (trace_id, session_id, sender_did, field_type,
                hop_count_a2a, hop_count_intra, score,
                dim1, dim2, dim3, dim4, breadth,
                severity, deviation_type, evidence_refs_json, hidden_state, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                score.get("trace_id", 0),
                score.get("session_id", ""),
                score.get("sender_did", ""),
                score.get("field_type", ""),
                hc[0], hc[1],
                score.get("score", 0.0),
                score.get("dim1", 0.0), score.get("dim2", 0.0),
                score.get("dim3", 0.0), score.get("dim4", 0.0),
                score.get("breadth", 0),
                score.get("severity", "none"),
                score.get("deviation_type", "none"),
                json.dumps(evidence_refs, ensure_ascii=False),
                score.get("hidden_state", ""),
                score.get("timestamp", 0.0),
            ),
        )
        return row_id

    async def query_hop_scores_by_session(self, session_id: str) -> list[dict]:
        """会话内全部逐跳评分，按 trace_id 升序。"""
        rows = await self._db.execute_fetch(
            "SELECT * FROM vertical_hop_scores WHERE session_id = ? ORDER BY trace_id",
            (session_id,),
        )
        return [self._shape_hop_row(r) for r in rows]

    async def query_hop_scores_by_did(
        self, did: str, since_id: int = 0,
    ) -> list[dict]:
        """某 DID 作为发送方的全部逐跳评分（since_id 之后），按 trace_id 升序。

        供横轴 W(σ) 取数与会话选择。
        """
        rows = await self._db.execute_fetch(
            "SELECT * FROM vertical_hop_scores WHERE sender_did = ? AND trace_id > ? ORDER BY trace_id",
            (did, since_id),
        )
        return [self._shape_hop_row(r) for r in rows]

    async def max_trace_id_for_did(self, did: str) -> int:
        """该 DID 已打分的最大 trace_id（横轴闭案时推进游标用）。"""
        row = await self._db.execute_fetchone(
            "SELECT MAX(trace_id) AS m FROM vertical_hop_scores WHERE sender_did = ?",
            (did,),
        )
        return (row["m"] or 0) if row else 0

    async def max_trace_id_for_session(self, session_id: str) -> int:
        """该会话已打分的最大 trace_id（纵轴游标恢复用）。"""
        row = await self._db.execute_fetchone(
            "SELECT MAX(trace_id) AS m FROM vertical_hop_scores WHERE session_id = ?",
            (session_id,),
        )
        return (row["m"] or 0) if row else 0

    @staticmethod
    def _shape_hop_row(row: dict) -> dict:
        """把存储行整理为对外一致的 dict（hop_count / dimensions / evidence_refs）。"""
        try:
            refs = json.loads(row.get("evidence_refs_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            refs = []
        row["hop_count"] = [row.pop("hop_count_a2a", 0), row.pop("hop_count_intra", 0)]
        row["dimensions"] = [
            row.pop("dim1", 0.0), row.pop("dim2", 0.0),
            row.pop("dim3", 0.0), row.pop("dim4", 0.0),
        ]
        row["evidence_refs"] = refs
        return row

    # ------------------------------------------------------------------
    # 纵向状态 vertical_analysis_states
    # ------------------------------------------------------------------

    async def save_vertical_state(self, session_id: str, state: dict) -> None:
        await self._db.execute(
            """INSERT OR REPLACE INTO vertical_analysis_states
               (session_id, initiator_did, intent_revisions_json, hidden_state,
                last_scored_trace_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                state.get("initiator_did", ""),
                state.get("intent_revisions_json", "[]"),
                state.get("hidden_state", ""),
                state.get("last_scored_trace_id", 0),
                _time.time(),
            ),
        )

    async def load_vertical_state(self, session_id: str) -> dict | None:
        return await self._db.execute_fetchone(
            "SELECT * FROM vertical_analysis_states WHERE session_id = ?",
            (session_id,),
        )
