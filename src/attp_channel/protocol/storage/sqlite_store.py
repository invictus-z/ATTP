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
                CREATE TABLE IF NOT EXISTS traces_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_did TEXT,
                    target_did TEXT,
                    session_id TEXT,
                    hop_count INTEGER,
                    signature TEXT,
                    timestamp REAL,
                    origin_did TEXT,
                    genesis_signature TEXT,
                    content TEXT
                )
            ''')
            conn.commit()

    def save_to_db(self, node_did: str, target_did: str,
                   session_id: str, hop_count: int,
                   signature: str, timestamp: float,
                   origin_did: str, genesis_signature: str,
                   content: str) -> None:
        """将日志条目存入数据库。"""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.execute('''
                INSERT INTO traces_v2 (node_did, target_did, session_id,
                                       hop_count, signature, timestamp,
                                       origin_did, genesis_signature, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (node_did, target_did, session_id, hop_count,
                  signature, timestamp, origin_did, genesis_signature,
                  content))
            conn.commit()

    def recover_trace(self, session_id: str) -> list:
        """按 session_id 恢复所有 trace 记录，按 hop_count DESC 排序。"""
        with sqlite3.connect(self.db_path, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM traces_v2 WHERE session_id = ? ORDER BY hop_count DESC",
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
                    "Hop_Count": int,
                    "Signature": str,
                    "Timestamp": float,
                    "Session_ID": str,
                    "origin_did": str,
                    "genesis_signature": str,
                    "Content": str,
                }

        Returns:
            bool: 存储成功返回 True，失败返回 False
        """
        try:
            self.save_to_db(
                node_did=log_entry.get("node_did"),
                target_did=log_entry.get("target_did"),
                session_id=log_entry.get("Session_ID"),
                hop_count=log_entry.get("Hop_Count"),
                signature=log_entry.get("Signature"),
                timestamp=log_entry.get("Timestamp"),
                origin_did=log_entry.get("origin_did"),
                genesis_signature=log_entry.get("genesis_signature"),
                content=log_entry.get("Content", ""),
            )
            logger.info(
                "Saved log to db: {} -> {}",
                log_entry.get("node_did"), log_entry.get("target_did"),
            )
            return True
        except Exception as e:
            logger.error("Failed to save log to db: {}", e)
            return False
