"""数据持久化：SQLite 存储层（异步）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import aiosqlite
from attp.app.logging import get_logger

logger = get_logger("Tracing")

# 累计违规次数 → severity_level 映射
_SEVERITY_THRESHOLDS = [
    (0, "clean"),
    (1, "warning"),
    (4, "dangerous"),
]  # 4+ → banned


def _severity_for_count(count: int) -> str:
    if count >= 4:
        return "banned"
    for threshold, level in reversed(_SEVERITY_THRESHOLDS):
        if count >= threshold:
            return level
    return "clean"


class SqliteStore:
    """Async SQLite-based trace log storage."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    async def create(cls, db_path: str | Path) -> SqliteStore:
        """Async factory: construct instance and initialise tables."""
        store = cls(db_path)
        await store._init_db()
        return store

    async def _init_db(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS behavior_traces (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    protocol_node_address  TEXT NOT NULL,
                    node_did    TEXT NOT NULL,
                    hop_count   INTEGER NOT NULL,
                    field_type  TEXT NOT NULL,
                    content     TEXT,
                    target      TEXT DEFAULT '',
                    timestamp   REAL,
                    extra       TEXT DEFAULT '{}'
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_bt_session
                    ON behavior_traces(session_id, protocol_node_address)
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_bt_hop
                    ON behavior_traces(session_id, protocol_node_address, hop_count)
            ''')

            # Analysis reports table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS analysis_reports (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id      TEXT NOT NULL,
                    batch_index     INTEGER NOT NULL,
                    report_json     TEXT NOT NULL,
                    from_trace_id   INTEGER NOT NULL,
                    to_trace_id     INTEGER NOT NULL,
                    timestamp       REAL
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_ar_session
                    ON analysis_reports(session_id)
            ''')

            # Analysis session state (survives restart)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS analysis_sessions (
                    session_id      TEXT PRIMARY KEY,
                    intent_json     TEXT,
                    report_count    INTEGER DEFAULT 0,
                    last_trace_id   INTEGER DEFAULT 0,
                    batch_index     INTEGER DEFAULT 0,
                    context         TEXT DEFAULT '',
                    updated_at      REAL
                )
            ''')

            # Per-DID 恶意节点档案
            await db.execute('''
                CREATE TABLE IF NOT EXISTS node_dossiers (
                    did                 TEXT PRIMARY KEY,
                    total_violations    INTEGER DEFAULT 0,
                    severity_level      TEXT DEFAULT 'clean',
                    first_seen_at       REAL,
                    last_seen_at        REAL,
                    evidence_breakdown  TEXT DEFAULT '{}',
                    last_evidence_type  TEXT DEFAULT '',
                    last_session_id     TEXT DEFAULT '',
                    last_evidence_desc  TEXT DEFAULT '',
                    updated_at          REAL
                )
            ''')

            await db.commit()
        logger.info("Database initialized at {}", self.db_path)

    async def _ensure_malicious_table(self) -> None:
        """Ensure the malicious_nodes table exists (idempotent)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS malicious_nodes (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id              TEXT NOT NULL,
                    malicious_did           TEXT NOT NULL,
                    evidence_type           TEXT NOT NULL,
                    evidence_description    TEXT,
                    severity                TEXT DEFAULT 'medium',
                    nonce                   TEXT,
                    timestamp               REAL,
                    raw_evidence            TEXT DEFAULT '{}'
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_mn_session
                    ON malicious_nodes(session_id)
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_mn_did
                    ON malicious_nodes(malicious_did)
            ''')
            await db.commit()

    # -- behavior_traces (a/b/c/d) --

    async def save_behavior_entry(
        self,
        session_id: str,
        protocol_node_address: str,
        node_did: str,
        hop_count: int,
        field_type: str,
        content: str,
        target: str = "",
        timestamp: float = 0.0,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Save a single a/b/c/d behavior entry."""
        extra_json = json.dumps(extra or {}, ensure_ascii=False)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO behavior_traces
                   (session_id, protocol_node_address, node_did, hop_count,
                    field_type, content, target, timestamp, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, protocol_node_address, node_did, hop_count,
                 field_type, content, target, timestamp, extra_json),
            )
            await db.commit()
        logger.debug(
            "Saved behavior entry: session={}, node={}, hop={}, field={}, target={}",
            session_id, node_did, hop_count, field_type, target,
        )

    async def recover_behavior_trace(
        self,
        session_id: str,
        protocol_node_address: str | None = None,
    ) -> list[dict]:
        """Recover all a/b/c/d entries for a session, ordered by hop_count."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if protocol_node_address:
                cursor = await db.execute(
                    """SELECT * FROM behavior_traces
                       WHERE session_id = ? AND protocol_node_address = ?
                       ORDER BY hop_count, timestamp""",
                    (session_id, protocol_node_address),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM behavior_traces
                       WHERE session_id = ?
                       ORDER BY hop_count, timestamp""",
                    (session_id,),
                )
            rows = await cursor.fetchall()
            result = [dict(r) for r in rows]
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
        """Get traces with id > since_id for a session.

        Returns (traces, max_id) where max_id is the largest id in the result,
        or since_id if no new traces exist.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM behavior_traces
                   WHERE session_id = ? AND id > ?
                   ORDER BY id""",
                (session_id, since_id),
            )
            rows = await cursor.fetchall()
            result = [dict(r) for r in rows]
            max_id = result[-1]["id"] if result else since_id
        return result, max_id

    # -- analysis_reports --

    async def save_analysis_report(self, report_json: str) -> None:
        """Save an analysis report."""
        report = json.loads(report_json)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO analysis_reports
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
            await db.commit()
        logger.info(
            "Saved analysis report: session={}, batch={}",
            report.get("session_id"), report.get("batch_index"),
        )

    async def recover_analysis_reports(self, session_id: str) -> list[dict]:
        """Recover all analysis reports for a session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM analysis_reports
                   WHERE session_id = ?
                   ORDER BY batch_index""",
                (session_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # -- analysis session state (persists across restarts) --

    async def save_analysis_session(self, session_id: str, state: dict) -> None:
        """Persist analysis state for a session (INSERT OR REPLACE)."""
        import time as _time
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO analysis_sessions
                   (session_id, intent_json, report_count, last_trace_id,
                    batch_index, context, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    state.get("intent_json"),
                    state.get("report_count", 0),
                    state.get("last_trace_id", 0),
                    state.get("batch_index", 0),
                    state.get("context", ""),
                    _time.time(),
                ),
            )
            await db.commit()

    async def load_analysis_session(self, session_id: str) -> dict | None:
        """Load persisted analysis state for a session."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT * FROM analysis_sessions WHERE session_id = ?""",
                (session_id,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    # -- malicious node reports --

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
        """Save a malicious node detection report and update the per-DID dossier."""
        await self._ensure_malicious_table()
        raw_json = json.dumps(raw_evidence or {}, ensure_ascii=False)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO malicious_nodes
                   (session_id, malicious_did, evidence_type, evidence_description,
                    severity, nonce, timestamp, raw_evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, malicious_did, evidence_type, evidence_description,
                 severity, nonce, timestamp, raw_json),
            )
            await db.commit()
        logger.info(
            "Saved malicious report: session={}, did={}, type={}, severity={}",
            session_id, malicious_did, evidence_type, severity,
        )
        # 自动更新 per-DID 档案
        await self.upsert_dossier(
            malicious_did, evidence_type, session_id, evidence_description,
        )

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list[dict]:
        """Query malicious node reports by session_id and/or did."""
        await self._ensure_malicious_table()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            conditions: list[str] = []
            params: list[Any] = []
            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)
            if malicious_did:
                conditions.append("malicious_did = ?")
                params.append(malicious_did)
            where = " AND ".join(conditions) if conditions else "1=1"
            cursor = await db.execute(
                f"""SELECT * FROM malicious_nodes WHERE {where}
                    ORDER BY timestamp DESC""",
                params,
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # -- node dossiers (per-DID 恶意节点档案) --

    async def upsert_dossier(
        self,
        malicious_did: str,
        evidence_type: str,
        session_id: str,
        description: str,
    ) -> None:
        """插入或更新节点档案。在 save_malicious_report 内部自动调用。"""
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT total_violations, evidence_breakdown, first_seen_at FROM node_dossiers WHERE did = ?",
                (malicious_did,),
            )
            row = await cursor.fetchone()

            if row is None:
                breakdown = {evidence_type: 1}
                await db.execute(
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
                severity = _severity_for_count(total)
                await db.execute(
                    """UPDATE node_dossiers
                       SET total_violations=?, severity_level=?, last_seen_at=?,
                           evidence_breakdown=?, last_evidence_type=?,
                           last_session_id=?, last_evidence_desc=?, updated_at=?
                       WHERE did=?""",
                    (
                        total, severity, now,
                        json.dumps(breakdown, ensure_ascii=False),
                        evidence_type, session_id, description, now,
                        malicious_did,
                    ),
                )
            await db.commit()
        logger.info(
            "Upserted dossier: did={}, evidence={}, total={}",
            malicious_did, evidence_type,
            1 if row is None else row["total_violations"] + 1,
        )

    async def query_dossier(self, did: str) -> dict | None:
        """查询单个 DID 的档案。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM node_dossiers WHERE did = ?", (did,),
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def query_all_dossiers(
        self,
        severity_level: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询所有档案，可按 severity_level 筛选。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if severity_level:
                cursor = await db.execute(
                    "SELECT * FROM node_dossiers WHERE severity_level = ? ORDER BY updated_at DESC LIMIT ?",
                    (severity_level, limit),
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM node_dossiers ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
