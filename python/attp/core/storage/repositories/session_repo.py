"""protocol_session_state 读写 — 验证状态持久化。"""

from __future__ import annotations

import json
import time as _time

from attp.app.logging import get_logger
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class ProtocolSessionRepository(BaseRepository):
    """protocol_session_state CRUD — completed_nonces / hop_count / trusted_dids。"""

    async def save_verification_state(self, session_id: str, state: dict) -> None:
        nonces_json = json.dumps(state.get("completed_nonces", []), ensure_ascii=False)
        hc = state.get("last_hop_count")
        hc_json = json.dumps(hc, ensure_ascii=False) if hc is not None else None
        dids_json = json.dumps(state.get("trusted_dids", []), ensure_ascii=False)

        await self._db.execute(
            """INSERT OR REPLACE INTO protocol_session_state
               (session_id, completed_nonces_json, last_hop_count_json,
                trusted_dids_json, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, nonces_json, hc_json, dids_json, _time.time()),
        )

    async def load_verification_state(self, session_id: str) -> dict | None:
        row = await self._db.execute_fetchone(
            "SELECT * FROM protocol_session_state WHERE session_id = ?",
            (session_id,),
        )
        if not row:
            return None
        return {
            "completed_nonces": json.loads(row["completed_nonces_json"]),
            "last_hop_count": json.loads(row["last_hop_count_json"]) if row["last_hop_count_json"] is not None else None,
            "trusted_dids": json.loads(row["trusted_dids_json"]),
        }

    async def delete_verification_state(self, session_id: str) -> None:
        await self._db.execute(
            "DELETE FROM protocol_session_state WHERE session_id = ?",
            (session_id,),
        )
