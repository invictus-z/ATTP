"""恶意节点查询 API 路由。"""

import json
import urllib.parse

from fastapi import APIRouter, Query

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("MaliciousAPI")


def _normalise_did(did: str) -> str:
    """将路径参数中的 DID 还原为 canonical form（%3A 编码端口）。

    FastAPI 会自动 URL-decode 路径参数，导致 ``localhost%3A8000`` 变为
    ``localhost:8000``，与数据库中存储的 canonical DID 不匹配。

    策略：将 ``did:wba:`` 之后、路径段之前的所有纯数字段视为端口号，
    将其重新编码为 ``domain%3Aport`` 格式。
    """
    # 已经包含 %3A，无需转换
    if "%3A" in did or "%3a" in did:
        return did

    parts = did.split(":")
    if len(parts) < 3 or parts[0] != "did":
        return did

    # did:wba:domain[:port]:segment:...
    # 如果 parts[3] 是纯数字，说明是端口号，需要合并到 domain 并 %3A 编码
    if parts[1] in ("wba", "web") and len(parts) >= 4 and parts[3].isdigit():
        domain = f"{parts[2]}%3A{parts[3]}"
        rest = parts[4:]
        return ":".join([parts[0], parts[1], domain] + rest)

    return did


def _format_report(r: dict) -> dict:
    """格式化单条 malicious_report 记录为 API 响应字段。"""
    raw = r.get("raw_evidence")
    return {
        "id": r["id"],
        "source": r.get("source", "protocol_review"),
        "target_did": r.get("target_did", r.get("malicious_did", "")),
        "node_type": r.get("node_type", ""),
        "session_id": r.get("session_id", ""),
        "evidence_type": r["evidence_type"],
        "severity": r.get("severity", "high"),
        "taint_score": r.get("taint_score", 0.0),
        "evidence_description": r.get("evidence_description", ""),
        "nonce": r.get("nonce", ""),
        "report_id": r.get("report_id"),
        "timestamp": r.get("timestamp"),
        "raw_evidence": json.loads(raw) if raw else {},
    }


def get_malicious_router(tracer: ProtocolTracer) -> APIRouter:
    router = APIRouter(prefix="/api/malicious")

    @router.get("/reports")
    async def query_reports(
        session_id: str | None = Query(None, description="按 session_id 筛选"),
        did: str | None = Query(None, description="按 DID 筛选"),
        source: str | None = Query(None, description="筛选来源: protocol_review / vertical_analysis / horizontal_analysis"),
        limit: int = Query(100, ge=1, le=1000),
    ):
        """统一查询恶意报告，支持 session_id / did / source 组合筛选。

        合并原 ``/session/{session_id}`` 与 ``/did/{did}`` 两个端点。
        """
        canonical = _normalise_did(did) if did else None
        try:
            reports = await tracer.query_malicious_reports(
                session_id=session_id, target_did=canonical, source=source,
            )
            if len(reports) > limit:
                reports = reports[:limit]
            return {
                "total": len(reports),
                "reports": [_format_report(r) for r in reports],
            }
        except Exception as e:
            logger.error("Error querying malicious reports: {}", e)
            return {"total": 0, "reports": []}

    # -- dossier 路由 --

    @router.get("/dossier/{did}")
    async def query_dossier(did: str):
        """查询指定 DID 的恶意节点档案（含违规明细）。"""
        canonical = _normalise_did(did)
        try:
            dossier = await tracer.query_dossier(canonical)
            if dossier is None:
                return {"did": did, "found": False}

            # 附带该 DID 的所有违规明细
            incidents = await tracer.query_malicious_reports(target_did=canonical)
            # 由 incidents 计算来源分布
            source_breakdown: dict[str, int] = {}
            for inc in incidents:
                src = inc.get("source", "unknown")
                source_breakdown[src] = source_breakdown.get(src, 0) + 1
            return {
                "found": True,
                "did": dossier["did"],
                "total_violations": dossier["total_violations"],
                "severity_level": dossier["severity_level"],
                "first_seen_at": dossier["first_seen_at"],
                "last_seen_at": dossier["last_seen_at"],
                "evidence_breakdown": json.loads(dossier.get("evidence_breakdown", "{}")),
                "source_breakdown": source_breakdown,
                "last_evidence_type": dossier["last_evidence_type"],
                "last_session_id": dossier["last_session_id"],
                "last_evidence_desc": dossier["last_evidence_desc"],
                "incidents": [_format_report(r) for r in incidents],
            }
        except Exception as e:
            logger.error("Error querying dossier for DID {}: {}", did, e)
            return {"did": did, "found": False}

    @router.get("/dossiers")
    async def query_all_dossiers(
        severity: str | None = Query(None, alias="severity"),
        source: str | None = Query(None, description="筛选来源: protocol_review / vertical_analysis / horizontal_analysis"),
        limit: int = Query(100, ge=1, le=1000),
    ):
        """查询所有恶意节点档案，可按 severity / source 筛选。

        每条档案附带 ``source_breakdown``（各来源违规计数），便于前端打标签。
        """
        try:
            dossiers = await tracer.query_all_dossiers(
                severity_level=severity, source=source, limit=limit,
            )
            return {
                "total": len(dossiers),
                "dossiers": [
                    {
                        "did": d["did"],
                        "total_violations": d["total_violations"],
                        "severity_level": d["severity_level"],
                        "first_seen_at": d["first_seen_at"],
                        "last_seen_at": d["last_seen_at"],
                        "evidence_breakdown": json.loads(d.get("evidence_breakdown", "{}")),
                        "source_breakdown": d.get("source_breakdown", {}),
                        "last_evidence_type": d["last_evidence_type"],
                        "last_session_id": d["last_session_id"],
                        "last_evidence_desc": d["last_evidence_desc"],
                    }
                    for d in dossiers
                ],
            }
        except Exception as e:
            logger.error("Error querying all dossiers: {}", e)
            return {"total": 0, "dossiers": []}

    return router
