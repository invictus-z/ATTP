"""恶意节点查询 API 路由。"""

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("MaliciousAPI")


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
                        "severity": r.get("severity", "medium"),
                        "nonce": r.get("nonce", ""),
                        "timestamp": r.get("timestamp"),
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
            reports = await tracer.query_malicious_nodes(malicious_did=did)
            return {
                "malicious_did": did,
                "reports": [
                    {
                        "id": r["id"],
                        "session_id": r["session_id"],
                        "evidence_type": r["evidence_type"],
                        "evidence_description": r.get("evidence_description", ""),
                        "severity": r.get("severity", "medium"),
                        "nonce": r.get("nonce", ""),
                        "timestamp": r.get("timestamp"),
                    }
                    for r in reports
                ],
                "total": len(reports),
            }
        except Exception as e:
            logger.error("Error querying malicious nodes for DID {}: {}", did, e)
            return {"malicious_did": did, "reports": [], "total": 0}

    return router
