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


def get_malicious_router(tracer: ProtocolTracer) -> APIRouter:
    router = APIRouter(prefix="/api/malicious")

    @router.get("/session/{session_id}")
    async def query_by_session(session_id: str):
        """查询指定 session 的恶意节点报告。"""
        try:
            reports = await tracer.query_malicious_nodes(session_id=session_id)
            return {
                "session_id": session_id,
                "reports": [
                    {
                        "id": r["id"],
                        "malicious_did": r["malicious_did"],
                        "evidence_type": r["evidence_type"],
                        "evidence_description": r.get("evidence_description", ""),
                        "nonce": r.get("nonce", ""),
                        "timestamp": r.get("timestamp"),
                        "raw_evidence": json.loads(r["raw_evidence"]) if r.get("raw_evidence") else {},
                    }
                    for r in reports
                ],
                "total": len(reports),
            }
        except Exception as e:
            logger.error("Error querying malicious nodes for {}: {}", session_id, e)
            return {"session_id": session_id, "reports": [], "total": 0}

    @router.get("/did/{did}")
    async def query_by_did(did: str):
        """查询指定 DID 的所有恶意节点报告。"""
        try:
            reports = await tracer.query_malicious_nodes(malicious_did=_normalise_did(did))
            return {
                "malicious_did": did,
                "reports": [
                    {
                        "id": r["id"],
                        "session_id": r["session_id"],
                        "evidence_type": r["evidence_type"],
                        "evidence_description": r.get("evidence_description", ""),
                        "nonce": r.get("nonce", ""),
                        "timestamp": r.get("timestamp"),
                        "raw_evidence": json.loads(r["raw_evidence"]) if r.get("raw_evidence") else {},
                    }
                    for r in reports
                ],
                "total": len(reports),
            }
        except Exception as e:
            logger.error("Error querying malicious nodes for DID {}: {}", did, e)
            return {"malicious_did": did, "reports": [], "total": 0}

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
            incidents = await tracer.query_malicious_nodes(malicious_did=canonical)
            return {
                "found": True,
                "did": dossier["did"],
                "total_violations": dossier["total_violations"],
                "severity_level": dossier["severity_level"],
                "first_seen_at": dossier["first_seen_at"],
                "last_seen_at": dossier["last_seen_at"],
                "evidence_breakdown": json.loads(dossier.get("evidence_breakdown", "{}")),
                "last_evidence_type": dossier["last_evidence_type"],
                "last_session_id": dossier["last_session_id"],
                "last_evidence_desc": dossier["last_evidence_desc"],
                "incidents": [
                    {
                        "session_id": r["session_id"],
                        "evidence_type": r["evidence_type"],
                        "evidence_description": r.get("evidence_description", ""),
                        "nonce": r.get("nonce", ""),
                        "timestamp": r.get("timestamp"),
                        "raw_evidence": json.loads(r["raw_evidence"]) if r.get("raw_evidence") else {},
                    }
                    for r in incidents
                ],
            }
        except Exception as e:
            logger.error("Error querying dossier for DID {}: {}", did, e)
            return {"did": did, "found": False}

    @router.get("/dossiers")
    async def query_all_dossiers(
        severity: str | None = Query(None, alias="severity"),
        limit: int = Query(100, ge=1, le=1000),
    ):
        """查询所有恶意节点档案，可按 severity 筛选。"""
        try:
            dossiers = await tracer.query_all_dossiers(
                severity_level=severity, limit=limit,
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
