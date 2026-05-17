"""malicious_nodes 和 node_dossiers 的读写。"""

from __future__ import annotations

import json
import time
from typing import Any

from attp.app.logging import get_logger
from attp.core.storage.database import severity_for_count
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class MaliciousRepository(BaseRepository):
    """malicious_nodes + node_dossiers CRUD。"""

    async def save_malicious_report(
        self,
        session_id: str,
        malicious_did: str,
        evidence_type: str,
        evidence_description: str = "",
        severity: str = "medium",
        nonce: str = "",
        timestamp: float = 0.0,
        raw_evidence: dict | None = None,
    ) -> None:
        raw_json = json.dumps(raw_evidence or {}, ensure_ascii=False)
        await self._db.execute(
            """INSERT INTO malicious_nodes
               (session_id, malicious_did, evidence_type, evidence_description,
                severity, nonce, timestamp, raw_evidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, malicious_did, evidence_type, evidence_description,
             severity, nonce, timestamp, raw_json),
        )
        logger.info(
            "Saved malicious report: session={}, did={}, type={}, severity={}",
            session_id, malicious_did, evidence_type, severity,
        )
        await self._upsert_dossier(
            malicious_did, evidence_type, session_id, evidence_description,
        )

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list[dict]:
        conditions: list[str] = []
        params: list[Any] = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if malicious_did:
            conditions.append("malicious_did = ?")
            params.append(malicious_did)
        where = " AND ".join(conditions) if conditions else "1=1"
        return await self._db.execute_fetch(
            f"SELECT * FROM malicious_nodes WHERE {where} ORDER BY timestamp DESC",
            tuple(params),
        )

    async def _upsert_dossier(
        self,
        malicious_did: str,
        evidence_type: str,
        session_id: str,
        description: str,
    ) -> None:
        now = time.time()
        row = await self._db.execute_fetchone(
            "SELECT total_violations, evidence_breakdown, first_seen_at FROM node_dossiers WHERE did = ?",
            (malicious_did,),
        )

        if row is None:
            breakdown = {evidence_type: 1}
            await self._db.execute(
                """INSERT INTO node_dossiers
                   (did, total_violations, severity_level, first_seen_at, last_seen_at,
                    evidence_breakdown, last_evidence_type, last_session_id,
                    last_evidence_desc, updated_at)
                   VALUES (?, 1, 'warning', ?, ?, ?, ?, ?, ?, ?)""",
                (
                    malicious_did, now, now,
                    json.dumps(breakdown, ensure_ascii=False),
                    evidence_type, session_id, description, now,
                ),
            )
        else:
            total = row["total_violations"] + 1
            breakdown = json.loads(row["evidence_breakdown"])
            breakdown[evidence_type] = breakdown.get(evidence_type, 0) + 1
            level = severity_for_count(total)
            await self._db.execute(
                """UPDATE node_dossiers
                   SET total_violations=?, severity_level=?, last_seen_at=?,
                       evidence_breakdown=?, last_evidence_type=?,
                       last_session_id=?, last_evidence_desc=?, updated_at=?
                   WHERE did=?""",
                (
                    total, level, now,
                    json.dumps(breakdown, ensure_ascii=False),
                    evidence_type, session_id, description, now,
                    malicious_did,
                ),
            )
        logger.info(
            "Upserted dossier: did={}, evidence={}, total={}",
            malicious_did, evidence_type,
            1 if row is None else row["total_violations"] + 1,
        )

    async def upsert_dossier(
        self,
        malicious_did: str,
        evidence_type: str,
        session_id: str,
        description: str,
    ) -> None:
        """公开接口，供外部直接调用。"""
        await self._upsert_dossier(malicious_did, evidence_type, session_id, description)

    async def query_dossier(self, did: str) -> dict | None:
        return await self._db.execute_fetchone(
            "SELECT * FROM node_dossiers WHERE did = ?", (did,),
        )

    async def query_all_dossiers(
        self,
        severity_level: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if severity_level:
            return await self._db.execute_fetch(
                "SELECT * FROM node_dossiers WHERE severity_level = ? ORDER BY updated_at DESC LIMIT ?",
                (severity_level, limit),
            )
        return await self._db.execute_fetch(
            "SELECT * FROM node_dossiers ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
