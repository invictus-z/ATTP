"""behavior_traces 表的读写。"""

from __future__ import annotations

import json
from typing import Any

from attp.app.logging import get_logger
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class TraceRepository(BaseRepository):
    """behavior_traces CRUD。"""

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
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        await self._db.execute(
            """INSERT INTO behavior_traces
               (session_id, protocol_node_address, node_did, hop_count_a2a,
                hop_count_intra, field_type, content, target, timestamp, extra)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, protocol_node_address, node_did, hop_count[0],
             hop_count[1], field_type, content, target, timestamp, extra_json),
        )
        logger.debug(
            "Saved behavior entry: session={}, node={}, hop={}, field={}, target={}",
            session_id, node_did, hop_count, field_type, target,
        )

    async def recover_behavior_trace(
        self,
        session_id: str,
        protocol_node_address: str | None = None,
    ) -> list[dict]:
        if protocol_node_address:
            rows = await self._db.execute_fetch(
                """SELECT * FROM behavior_traces
                   WHERE session_id = ? AND protocol_node_address = ?
                   ORDER BY hop_count_a2a, hop_count_intra, timestamp""",
                (session_id, protocol_node_address),
            )
        else:
            rows = await self._db.execute_fetch(
                """SELECT * FROM behavior_traces
                   WHERE session_id = ?
                   ORDER BY hop_count_a2a, hop_count_intra, timestamp""",
                (session_id,),
            )
        result = []
        for row in rows:
            row["hop_count"] = [row.pop("hop_count_a2a", 0), row.pop("hop_count_intra", 0)]
            result.append(row)
        logger.debug(
            "Recovered behavior trace: session={}, pna={}, count={}",
            session_id, protocol_node_address, len(result),
        )
        return result

    async def recover_traces_since(
        self,
        session_id: str,
        since_id: int,
    ) -> tuple[list[dict], int]:
        result = await self._db.execute_fetch(
            """SELECT * FROM behavior_traces
               WHERE session_id = ? AND id > ?
               ORDER BY id""",
            (session_id, since_id),
        )
        max_id = result[-1]["id"] if result else since_id
        return result, max_id
