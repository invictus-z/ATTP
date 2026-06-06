"""aiosqlite 连接管理、表结构初始化。"""

from __future__ import annotations

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


def severity_for_count(count: int) -> str:
    if count >= 4:
        return "banned"
    for threshold, level in reversed(_SEVERITY_THRESHOLDS):
        if count >= threshold:
            return level
    return "clean"


class Database:
    """管理 aiosqlite 连接，提供 execute / query 便捷方法。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """执行全部 DDL（建表 + 索引）。"""
        async with aiosqlite.connect(self.db_path) as db:
            # behavior_traces
            await db.execute('''
                CREATE TABLE IF NOT EXISTS behavior_traces (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id  TEXT NOT NULL,
                    protocol_node_address  TEXT NOT NULL,
                    node_did    TEXT NOT NULL,
                    hop_count_a2a   INTEGER NOT NULL,
                    hop_count_intra INTEGER NOT NULL,
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
                    ON behavior_traces(session_id, protocol_node_address, hop_count_a2a, hop_count_intra)
            ''')

            # ---- Cross-Lock: 纵向表重命名迁移（旧表 → vertical_ 前缀） ----
            # 兼容旧数据库：如果旧表存在则重命名
            await self._migrate_vertical_tables(db)

            # vertical_analysis_reports（原 analysis_reports）
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vertical_analysis_reports (
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
                CREATE INDEX IF NOT EXISTS idx_var_session
                    ON vertical_analysis_reports(session_id)
            ''')

            # vertical_analysis_states（原 analysis_sessions）
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vertical_analysis_states (
                    session_id      TEXT PRIMARY KEY,
                    intent_json     TEXT,
                    report_count    INTEGER DEFAULT 0,
                    last_trace_id   INTEGER DEFAULT 0,
                    batch_index     INTEGER DEFAULT 0,
                    context         TEXT DEFAULT '',
                    updated_at      REAL
                )
            ''')

            # ---- Cross-Lock: 横向分析新增表 ----

            # horizontal_analysis_states（per-DID）
            await db.execute('''
                CREATE TABLE IF NOT EXISTS horizontal_analysis_states (
                    did                 TEXT PRIMARY KEY,
                    node_type           TEXT NOT NULL DEFAULT 'agent',
                    accumulated_count   INTEGER NOT NULL DEFAULT 0,
                    last_trace_id       INTEGER NOT NULL DEFAULT 0,
                    batch_index         INTEGER NOT NULL DEFAULT 0,
                    context             TEXT NOT NULL DEFAULT '',
                    updated_at          REAL NOT NULL
                )
            ''')

            # horizontal_analysis_reports
            await db.execute('''
                CREATE TABLE IF NOT EXISTS horizontal_analysis_reports (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    did             TEXT NOT NULL,
                    node_type       TEXT NOT NULL,
                    batch_index     INTEGER NOT NULL DEFAULT 0,
                    report_json     TEXT NOT NULL,
                    from_trace_id   INTEGER NOT NULL DEFAULT 0,
                    to_trace_id     INTEGER NOT NULL DEFAULT 0,
                    sessions_scanned INTEGER NOT NULL DEFAULT 0,
                    timestamp       REAL
                )
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_hor_did
                    ON horizontal_analysis_reports(did)
            ''')
            await db.execute('''
                CREATE INDEX IF NOT EXISTS idx_hor_did_batch
                    ON horizontal_analysis_reports(did, batch_index)
            ''')

            # node_dossiers
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

            # malicious_nodes
            await db.execute('''
                CREATE TABLE IF NOT EXISTS malicious_nodes (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id              TEXT NOT NULL,
                    malicious_did           TEXT NOT NULL,
                    evidence_type           TEXT NOT NULL,
                    evidence_description    TEXT,
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

            # protocol_session_state — 验证状态持久化
            await db.execute('''
                CREATE TABLE IF NOT EXISTS protocol_session_state (
                    session_id              TEXT PRIMARY KEY,
                    completed_nonces_json   TEXT NOT NULL DEFAULT '[]',
                    hop_count_map_json      TEXT DEFAULT NULL,
                    trusted_dids_json       TEXT NOT NULL DEFAULT '[]',
                    updated_at              REAL NOT NULL
                )
            ''')

            await db.commit()
        logger.info("Database initialized at {}", self.db_path)

    @staticmethod
    async def _migrate_vertical_tables(db) -> None:
        """Migrate old table names to vertical_ prefixed names (idempotent)."""
        # Check if old tables exist and new ones don't
        async def _table_exists(name: str) -> bool:
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
            )
            row = await cursor.fetchone()
            return row is not None

        # Migrate analysis_reports → vertical_analysis_reports
        if await _table_exists("analysis_reports") and not await _table_exists("vertical_analysis_reports"):
            await db.execute("ALTER TABLE analysis_reports RENAME TO vertical_analysis_reports")
            await db.execute("DROP INDEX IF EXISTS idx_ar_session")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_var_session ON vertical_analysis_reports(session_id)")
            logger.info("Migrated: analysis_reports → vertical_analysis_reports")

        # Migrate analysis_sessions → vertical_analysis_states
        if await _table_exists("analysis_sessions") and not await _table_exists("vertical_analysis_states"):
            await db.execute("ALTER TABLE analysis_sessions RENAME TO vertical_analysis_states")
            logger.info("Migrated: analysis_sessions → vertical_analysis_states")

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """执行写操作并自动 commit。"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()

    async def execute_fetch(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> list[dict]:
        """执行查询，返回 list[dict]。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def execute_fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> dict | None:
        """执行查询，返回单行 dict 或 None。"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(sql, params)
            row = await cursor.fetchone()
            return dict(row) if row else None
