"""数据持久化：SQLite 存储层。"""

import sqlite3
from pathlib import Path

from attp_channel.logging import get_logger

logger = get_logger("Tracing")


class SqliteStore:
    """SQLite-based trace log storage."""

    def __init__(self, db_path: str = "attp_traces.db"):
        self.db_path = Path.home() / ".nanobot" / db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_did TEXT,
                    target_did TEXT,
                    entry_hash TEXT,
                    prev_hash TEXT,
                    session_id TEXT,
                    hop_count INTEGER,
                    content_snapshot TEXT,
                    signature TEXT,
                    timestamp REAL
                )
            ''')
            conn.commit()

    def save_to_db(self, node_did: str, target_did: str, entry_hash: str,
                   prev_hash: str, session_id: str, hop_count: int,
                   content_snapshot: str, signature: str, timestamp: float) -> None:
        """将日志条目存入数据库。"""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute('''
                INSERT INTO traces (node_did, target_did, entry_hash, prev_hash,
                                    session_id, hop_count, content_snapshot, signature, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (node_did, target_did, entry_hash, prev_hash,
                  session_id, hop_count, content_snapshot, signature, timestamp))
            conn.commit()

    def recover_trace(self, session_id: str) -> list:
        """按 session_id 恢复所有 trace 记录，按 hop_count DESC 排序。"""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM traces WHERE session_id = ? ORDER BY hop_count DESC",
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_log_to_db(self, log_entry: dict) -> bool:
        """将单个 log 条目存入数据库（用于 record 类型消息）。

        Args:
            log_entry: 包含日志信息的字典，格式为:
                {
                    "node_did": str,
                    "target_did": str,
                    "Entry_Hash": str,
                    "Prev_Hash": str,
                    "Session_ID": str,
                    "Hop_Count": int,
                    "Content_Snapshot": str,
                    "Signature": str,
                    "Timestamp": float
                }

        Returns:
            bool: 存储成功返回 True，失败返回 False
        """
        try:
            self.save_to_db(
                node_did=log_entry.get("node_did"),
                target_did=log_entry.get("target_did"),
                entry_hash=log_entry.get("Entry_Hash"),
                prev_hash=log_entry.get("Prev_Hash"),
                session_id=log_entry.get("Session_ID"),
                hop_count=log_entry.get("Hop_Count"),
                content_snapshot=log_entry.get("Content_Snapshot"),
                signature=log_entry.get("Signature"),
                timestamp=log_entry.get("Timestamp"),
            )
            logger.info(
                "Saved log to db: {} -> {}",
                log_entry.get("node_did"), log_entry.get("target_did"),
            )
            return True
        except Exception as e:
            logger.error("Failed to save log to db: {}", e)
            return False
