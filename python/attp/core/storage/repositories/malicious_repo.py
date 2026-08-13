"""malicious_reports 和 node_dossiers 的读写。"""

from __future__ import annotations

import json
import time
from typing import Any

from attp.app.logging import get_logger
from attp.core.storage.database import severity_for_count
from attp.core.storage.repositories.base import BaseRepository

logger = get_logger("Tracing")


class MaliciousRepository(BaseRepository):
    """malicious_reports + node_dossiers CRUD。"""

    async def save_malicious_report(self, report: dict) -> int:
        """统一写入 malicious_reports 表，同时调用 _upsert_dossier。

        Args:
            report: 包含以下 key 的字典:
                source, target_did, node_type, session_id, evidence_type,
                severity, taint_score, evidence_description, nonce,
                report_id, raw_evidence, timestamp

        Returns:
            插入行的 id。
        """
        raw_json = json.dumps(report.get("raw_evidence") or {}, ensure_ascii=False)
        row_id = await self._db.execute_insert(
            """INSERT INTO malicious_reports
               (source, target_did, node_type, session_id, evidence_type,
                severity, taint_score, evidence_description, nonce,
                report_id, raw_evidence, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report["source"],
                report["target_did"],
                report.get("node_type", ""),
                report.get("session_id", ""),
                report["evidence_type"],
                report.get("severity", "medium"),
                report.get("taint_score", 0.0),
                report.get("evidence_description", ""),
                report.get("nonce", ""),
                report.get("report_id"),
                raw_json,
                report.get("timestamp", 0.0),
            ),
        )
        logger.info(
            "Saved malicious report: source={}, did={}, type={}, severity={}",
            report["source"], report["target_did"],
            report["evidence_type"], report.get("severity", "medium"),
        )
        await self._upsert_dossier(
            report["target_did"],
            report["evidence_type"],
            report.get("session_id", ""),
            report.get("evidence_description", ""),
        )
        return row_id

    async def query_malicious_reports(
        self,
        session_id: str | None = None,
        target_did: str | None = None,
        source: str | None = None,
    ) -> list[dict]:
        """按条件查询恶意报告，支持 source 筛选。"""
        conditions: list[str] = []
        params: list[Any] = []
        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if target_did:
            conditions.append("target_did = ?")
            params.append(target_did)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if not conditions:
            sql = "SELECT * FROM malicious_reports ORDER BY timestamp DESC"
        else:
            sql = (
                "SELECT * FROM malicious_reports WHERE "
                + " AND ".join(conditions)
                + " ORDER BY timestamp DESC"
            )
        return await self._db.execute_fetch(sql, tuple(params))

    # -- 兼容旧接口（委托到新方法） --

    async def query_malicious_nodes(
        self,
        session_id: str | None = None,
        malicious_did: str | None = None,
    ) -> list[dict]:
        """兼容旧接口: query_malicious_nodes → query_malicious_reports。"""
        return await self.query_malicious_reports(
            session_id=session_id, target_did=malicious_did,
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
            if session_id:
                # 有 session_id 时更新全部字段
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
            else:
                # 无 session_id（如横向分析跨 session）只更新统计和等级，保留已有 session 信息
                await self._db.execute(
                    """UPDATE node_dossiers
                       SET total_violations=?, severity_level=?, last_seen_at=?,
                           evidence_breakdown=?, last_evidence_type=?,
                           updated_at=?
                       WHERE did=?""",
                    (
                        total, level, now,
                        json.dumps(breakdown, ensure_ascii=False),
                        evidence_type, now,
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
        source: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询所有档案，可按 severity_level 和 source 筛选。

        source 筛选语义：只返回"至少有一条来自该来源 incident"的档案
        （通过 malicious_reports 子查询判定）。
        """
        conditions: list[str] = []
        params: list[Any] = []
        if severity_level:
            conditions.append("severity_level = ?")
            params.append(severity_level)
        if source:
            conditions.append(
                "did IN (SELECT DISTINCT target_did FROM malicious_reports WHERE source = ?)"
            )
            params.append(source)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"SELECT * FROM node_dossiers{where} ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        return await self._db.execute_fetch(sql, tuple(params))

    async def compute_source_breakdown(self) -> dict[str, dict[str, int]]:
        """返回 {did: {source: count}} 映射，用于给 dossier 补来源分布。

        一条 GROUP BY 查询拉全表，调用方按需取涉及的 did。
        """
        rows = await self._db.execute_fetch(
            "SELECT target_did, source, COUNT(*) AS cnt "
            "FROM malicious_reports GROUP BY target_did, source"
        )
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            did = row["target_did"]
            result.setdefault(did, {})[row["source"]] = row["cnt"]
        return result
