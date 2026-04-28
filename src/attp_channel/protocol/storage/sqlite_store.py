"""数据持久化：SQLite 存储层。"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from attp_channel.logging import get_logger
from attp_channel.sessions.node_message import NodeMessage

logger = get_logger("Tracing")


class SqliteStore:
    """SQLite-based trace log storage."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute('''
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
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_bt_session
                    ON behavior_traces(session_id, origin_did)
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_bt_hop
                    ON behavior_traces(session_id, origin_did, hop_count)
            ''')

            # Analysis reports table
            conn.execute('''
                CREATE TABLE IF NOT EXISTS analysis_reports (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id      TEXT NOT NULL,
                    batch_index     INTEGER NOT NULL,
                    report_json     TEXT NOT NULL,
                    context_summary TEXT DEFAULT '',
                    from_trace_id   INTEGER NOT NULL,
                    to_trace_id     INTEGER NOT NULL,
                    timestamp       REAL
                )
            ''')
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_ar_session
                    ON analysis_reports(session_id)
            ''')
            conn.commit()
        logger.info("Database initialized at {}", self.db_path)

    # -- behavior_traces (a/b/c/d) --

    def save_behavior_entry(
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
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute(
                """INSERT INTO behavior_traces
                   (session_id, origin_did, node_did, hop_count,
                    field_type, content, target, timestamp, extra)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, origin_did, node_did, hop_count,
                 field_type, content, target, timestamp, extra_json),
            )
            conn.commit()
        logger.debug(
            "Saved behavior entry: session={}, node={}, hop={}, field={}, target={}",
            session_id, node_did, hop_count, field_type, target,
        )

    def save_node_message(self, node_message: NodeMessage) -> None:
        """Bulk-save all entries from a NodeMessage (called at Genesis)."""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            for entry in node_message.entries:
                extra_json = json.dumps(entry.extra, ensure_ascii=False)
                conn.execute(
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
            conn.commit()
        logger.info(
            "Saved NodeMessage: session={}, node={}, hop={}, entries={}",
            node_message.session_id, node_message.node_did,
            node_message.hop_count, len(node_message.entries),
        )

    def recover_behavior_trace(
        self,
        session_id: str,
        origin_did: str | None = None,
    ) -> list[dict]:
        """Recover all a/b/c/d entries for a session, ordered by hop_count."""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            if origin_did:
                rows = conn.execute(
                    """SELECT * FROM behavior_traces
                       WHERE session_id = ? AND origin_did = ?
                       ORDER BY hop_count, timestamp""",
                    (session_id, origin_did),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM behavior_traces
                       WHERE session_id = ?
                       ORDER BY hop_count, timestamp""",
                    (session_id,),
                ).fetchall()
            result = [dict(r) for r in rows]
        logger.debug(
            "Recovered behavior trace: session={}, origin={}, count={}",
            session_id, origin_did, len(result),
        )
        return result

    def recover_traces_since(
        self,
        session_id: str,
        since_id: int,
    ) -> tuple[list[dict], int]:
        """Get traces with id > since_id for a session.

        Returns (traces, max_id) where max_id is the largest id in the result,
        or since_id if no new traces exist.
        """
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM behavior_traces
                   WHERE session_id = ? AND id > ?
                   ORDER BY id""",
                (session_id, since_id),
            ).fetchall()
            result = [dict(r) for r in rows]
            max_id = result[-1]["id"] if result else since_id
        return result, max_id

    # -- analysis_reports --

    def save_analysis_report(self, report_json: str, context_summary: str = "") -> None:
        """Save an analysis report."""
        report = json.loads(report_json)
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute(
                """INSERT INTO analysis_reports
                   (session_id, batch_index, report_json, context_summary,
                    from_trace_id, to_trace_id, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    report.get("session_id", ""),
                    report.get("batch_index", 0),
                    report_json,
                    context_summary,
                    report.get("from_trace_id", 0),
                    report.get("to_trace_id", 0),
                    report.get("timestamp", 0.0),
                ),
            )
            conn.commit()
        logger.info(
            "Saved analysis report: session={}, batch={}",
            report.get("session_id"), report.get("batch_index"),
        )

    def recover_analysis_reports(self, session_id: str) -> list[dict]:
        """Recover all analysis reports for a session."""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM analysis_reports
                   WHERE session_id = ?
                   ORDER BY batch_index""",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]
