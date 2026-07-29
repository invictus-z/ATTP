"""aiosqlite 连接管理、表结构初始化（逐跳有状态改版）。"""

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
        """执行全部 DDL（建表 + 索引 + 幂等迁移）。"""
        async with aiosqlite.connect(self.db_path) as db:
            # ---- 旧表结构归一化（无向后兼容：旧形状直接 DROP+CREATE） ----
            await self._normalize_legacy_tables(db)

            # behavior_traces（不变）
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

            # vertical_hop_scores（新增）—— 逐跳 V-Reasoner 评分结果
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vertical_hop_scores (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id        INTEGER NOT NULL,
                    session_id      TEXT NOT NULL,
                    sender_did      TEXT NOT NULL,
                    field_type      TEXT NOT NULL,
                    hop_count_a2a   INTEGER NOT NULL,
                    hop_count_intra INTEGER NOT NULL,
                    score           REAL NOT NULL DEFAULT 0,
                    dim1            REAL NOT NULL DEFAULT 0,
                    dim2            REAL NOT NULL DEFAULT 0,
                    dim3            REAL NOT NULL DEFAULT 0,
                    dim4            REAL NOT NULL DEFAULT 0,
                    breadth         INTEGER NOT NULL DEFAULT 0,
                    severity        TEXT NOT NULL DEFAULT 'none',
                    deviation_type  TEXT NOT NULL DEFAULT 'none',
                    evidence_refs_json TEXT NOT NULL DEFAULT '[]',
                    hidden_state    TEXT NOT NULL DEFAULT '',
                    timestamp       REAL
                )
            ''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vhs_session ON vertical_hop_scores(session_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vhs_sender ON vertical_hop_scores(sender_did)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_vhs_trace ON vertical_hop_scores(trace_id)"
            )

            # vertical_analysis_states（重定义：意图流 + 隐状态 + 打分游标）
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vertical_analysis_states (
                    session_id              TEXT PRIMARY KEY,
                    initiator_did           TEXT DEFAULT '',
                    intent_revisions_json   TEXT DEFAULT '[]',
                    hidden_state            TEXT DEFAULT '',
                    last_scored_trace_id    INTEGER DEFAULT 0,
                    updated_at              REAL
                )
            ''')

            # horizontal_analysis_states（重定义：per-DID F 累加 + 体积 + 确认游标）
            await db.execute('''
                CREATE TABLE IF NOT EXISTS horizontal_analysis_states (
                    did                 TEXT PRIMARY KEY,
                    node_type           TEXT NOT NULL DEFAULT 'agent',
                    f_value             REAL NOT NULL DEFAULT 0,
                    volume              INTEGER NOT NULL DEFAULT 0,
                    last_trace_id       INTEGER NOT NULL DEFAULT 0,
                    batch_index         INTEGER NOT NULL DEFAULT 0,
                    context             TEXT NOT NULL DEFAULT '',
                    updated_at          REAL NOT NULL
                )
            ''')

            # horizontal_analysis_reports（确认报告，形状变化仅在 report_json）
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
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_hor_did ON horizontal_analysis_reports(did)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_hor_did_batch ON horizontal_analysis_reports(did, batch_index)"
            )

            # node_dossiers（不变）
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

            # malicious_reports（不变；taint_score 值域 0–10、severity 5 档为值变化）
            await db.execute('''
                CREATE TABLE IF NOT EXISTS malicious_reports (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    source                  TEXT NOT NULL,
                    target_did              TEXT NOT NULL,
                    node_type               TEXT NOT NULL DEFAULT '',
                    session_id              TEXT NOT NULL DEFAULT '',
                    evidence_type           TEXT NOT NULL,
                    severity                TEXT NOT NULL DEFAULT 'medium',
                    taint_score             REAL NOT NULL DEFAULT 0.0,
                    evidence_description    TEXT NOT NULL DEFAULT '',
                    nonce                   TEXT DEFAULT '',
                    report_id               INTEGER DEFAULT NULL,
                    raw_evidence            TEXT DEFAULT '{}',
                    timestamp               REAL
                )
            ''')
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mr_session ON malicious_reports(session_id)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mr_did ON malicious_reports(target_did)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_mr_source ON malicious_reports(source)"
            )

            # ---- 迁移：malicious_nodes → malicious_reports（保留，兼容旧库）----
            await self._migrate_malicious_nodes(db)

            # protocol_session_state — 验证状态持久化（不变）
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
    async def _column_exists(db, table: str, column: str) -> bool:
        cursor = await db.execute(f"PRAGMA table_info({table})")
        rows = await cursor.fetchall()
        return any(r[1] == column for r in rows)

    @staticmethod
    async def _table_exists(db, name: str) -> bool:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        row = await cursor.fetchone()
        return row is not None

    @staticmethod
    async def _normalize_legacy_tables(db) -> None:
        """把旧版表结构归一到新 schema（幂等、无向后兼容）。

        - 删除已废弃的 vertical_analysis_reports / analysis_reports（无批次报告）。
        - 若 vertical_analysis_states 缺新标记列 intent_revisions_json → DROP（随后重建）。
          同时清理旧名 analysis_sessions。
        - 若 horizontal_analysis_states 缺新标记列 f_value → DROP（随后重建）。
        """
        async def _drop_if_exists(name: str) -> None:
            if await Database._table_exists(db, name):
                await db.execute(f"DROP TABLE IF EXISTS {name}")
                logger.info("Dropped legacy table: {}", name)

        # 已废弃的报告表
        await _drop_if_exists("vertical_analysis_reports")
        await _drop_if_exists("analysis_reports")

        # 纵向状态表：旧形状（无 intent_revisions_json）→ 删除重建
        if await Database._table_exists(db, "vertical_analysis_states"):
            if not await Database._column_exists(db, "vertical_analysis_states", "intent_revisions_json"):
                await db.execute("DROP TABLE vertical_analysis_states")
                logger.info("Dropped legacy vertical_analysis_states (will recreate with new schema)")
        await _drop_if_exists("analysis_sessions")

        # 横向状态表：旧形状（无 f_value）→ 删除重建
        if await Database._table_exists(db, "horizontal_analysis_states"):
            if not await Database._column_exists(db, "horizontal_analysis_states", "f_value"):
                await db.execute("DROP TABLE horizontal_analysis_states")
                logger.info("Dropped legacy horizontal_analysis_states (will recreate with new schema)")

    @staticmethod
    async def _migrate_malicious_nodes(db) -> None:
        """Migrate malicious_nodes → malicious_reports (idempotent, 兼容旧库)。"""
        if not await Database._table_exists(db, "malicious_nodes"):
            return
        if await Database._table_exists(db, "malicious_reports"):
            # 已有新表，旧表残留则直接丢弃
            await db.execute("DROP TABLE IF EXISTS malicious_nodes")
            return

        await db.execute("ALTER TABLE malicious_nodes RENAME TO malicious_reports")
        if not await Database._column_exists(db, "malicious_reports", "source"):
            await db.execute(
                "ALTER TABLE malicious_reports ADD COLUMN source TEXT NOT NULL DEFAULT 'protocol_review'"
            )
        if not await Database._column_exists(db, "malicious_reports", "node_type"):
            await db.execute("ALTER TABLE malicious_reports ADD COLUMN node_type TEXT NOT NULL DEFAULT ''")
        if not await Database._column_exists(db, "malicious_reports", "severity"):
            await db.execute("ALTER TABLE malicious_reports ADD COLUMN severity TEXT NOT NULL DEFAULT 'medium'")
        if not await Database._column_exists(db, "malicious_reports", "taint_score"):
            await db.execute("ALTER TABLE malicious_reports ADD COLUMN taint_score REAL NOT NULL DEFAULT 0.0")
        if not await Database._column_exists(db, "malicious_reports", "report_id"):
            await db.execute("ALTER TABLE malicious_reports ADD COLUMN report_id INTEGER DEFAULT NULL")
        await db.execute("ALTER TABLE malicious_reports RENAME COLUMN malicious_did TO target_did")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mr_did ON malicious_reports(target_did)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mr_source ON malicious_reports(source)")
        await db.execute("DROP INDEX IF EXISTS idx_mn_session")
        await db.execute("DROP INDEX IF EXISTS idx_mn_did")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_mr_session ON malicious_reports(session_id)")
        logger.info("Migrated: malicious_nodes → malicious_reports")

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """执行写操作并自动 commit。"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(sql, params)
            await db.commit()

    async def execute_insert(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """执行 INSERT 并返回 lastrowid。"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(sql, params)
            await db.commit()
            return cursor.lastrowid

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
