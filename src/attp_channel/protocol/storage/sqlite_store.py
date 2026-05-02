"""数据持久化：SQLite 存储层（异步）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite

from attp_channel.logging import get_logger
from attp_channel.sessions.node_message import NodeMessage

logger = get_logger("Tracing")


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
                    origin_did  TEXT NOT NULL,
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
                    ON behavior_traces(session_id, origin_did)
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_bt_hop
                    ON behavior_traces(session_id, origin_did, hop_count)
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
            await db.commit()
        logger.info("Database initialized at {}", self.db_path)

    # -- behavior_traces (a/b/c/d) --

    async def save_behavior_entry(
        self,
        session_id: str,
        origin_did: str,
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
                   (session_id, origin_did, node_did, hop_count,
                    field_type, content, target, timestamp, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, origin_did, node_did, hop_count,
                 field_type, content, target, timestamp, extra_json),
            )
            await db.commit()
        logger.debug(
            "Saved behavior entry: session={}, node={}, hop={}, field={}, target={}",
            session_id, node_did, hop_count, field_type, target,
        )

    async def save_node_message(self, node_message: NodeMessage) -> None:
        """Bulk-save all entries from a NodeMessage (called at Genesis)."""
        async with aiosqlite.connect(self.db_path) as db:
            for entry in node_message.entries:
                extra_json = json.dumps(entry.extra, ensure_ascii=False)
                await db.execute(
                    """INSERT INTO behavior_traces
                       (session_id, origin_did, node_did, hop_count,
                        field_type, content, target, timestamp, extra)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (node_message.session_id,
                     node_message.origin_did,
                     node_message.node_did,
                     node_message.hop_count,
                     entry.field_type,
                     entry.content,
                     entry.target,
                     entry.timestamp,
                     extra_json),
                )
            await db.commit()
        logger.info(
            "Saved NodeMessage: session={}, node={}, hop={}, entries={}",
            node_message.session_id, node_message.node_did,
            node_message.hop_count, len(node_message.entries),
        )

    async def recover_behavior_trace(
        self,
        session_id: str,
        origin_did: str | None = None,
    ) -> list[dict]:
        """Recover all a/b/c/d entries for a session, ordered by hop_count."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if origin_did:
                cursor = await db.execute(
                    """SELECT * FROM behavior_traces
                       WHERE session_id = ? AND origin_did = ?
                       ORDER BY hop_count, timestamp""",
                    (session_id, origin_did),
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
            "Recovered behavior trace: session={}, origin={}, count={}",
            session_id, origin_did, len(result),
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
