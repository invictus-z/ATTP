"""协议相关 API 路由 — Health check + 行为溯源。"""

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("Tracing")

_SENDER_TYPE_MAP = {"A": "agent", "U": "user", "T": "tool"}


def get_behavior_router(
    tracer: ProtocolTracer,
) -> APIRouter:
    router = APIRouter(prefix="/api")

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @router.get("/status")
    async def get_status():
        """Health check endpoint for protocol node connectivity detection."""
        return {
            "status": "ok",
            "service": "protocol_node",
        }

    @router.get("/behavior/{session_id}")
    async def get_behavior_trace(session_id: str, protocol_node_address: str | None = None):
        """Return full behavior trace as a flat chain ordered by hop_count."""
        try:
            entries = await tracer.recover_behavior_trace(session_id, protocol_node_address)

            chain = []
            for row in entries:
                ft = row["field_type"]
                chain.append({
                    "hop_count": row["hop_count"],
                    "field_type": ft,
                    "sender_type": _SENDER_TYPE_MAP.get(ft[0], "unknown"),
                    "sender_did": row["sender_did"],
                    "target_did": row.get("target_did", ""),
                    "content": row.get("content", ""),
                    "timestamp": row.get("timestamp"),
                })

            return {
                "session_id": session_id,
                "protocol_node_address": protocol_node_address,
                "chain": chain,
            }
        except Exception as e:
            logger.error("Error recovering behavior trace for {}: {}", session_id, e)
            return {
                "session_id": session_id,
                "protocol_node_address": protocol_node_address,
                "chain": [],
            }

    return router
