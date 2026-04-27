from datetime import datetime
from fastapi import APIRouter

from attp_channel.logging import get_logger
from attp_channel.protocol.tracer import MessageTracer

logger = get_logger("Tracing")


def get_behavior_router(tracer: MessageTracer) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/behavior/{session_id}")
    async def get_behavior_trace(session_id: str, origin_did: str = None):
        """Return full behavior trace: a/b/c/d entries grouped by hop_count."""
        try:
            entries = tracer.recover_behavior_trace(session_id, origin_did)

            nodes: dict[int, dict] = {}
            for row in entries:
                hc = row["hop_count"]
                if hc not in nodes:
                    nodes[hc] = {
                        "hop_count": hc,
                        "node_did": row["node_did"],
                        "a": [],
                        "b": [],
                        "c": [],
                        "d": [],
                    }
                ft = row["field_type"]
                if ft in nodes[hc]:
                    nodes[hc][ft].append({
                        "content": row.get("content", ""),
                        "target": row.get("target", ""),
                        "timestamp": row.get("timestamp"),
                    })

            return {
                "session_id": session_id,
                "origin_did": origin_did,
                "nodes": sorted(nodes.values(), key=lambda n: n["hop_count"]),
            }
        except Exception as e:
            logger.error("Error recovering behavior trace for {}: {}", session_id, e)
            return {
                "session_id": session_id,
                "origin_did": origin_did,
                "nodes": [],
            }

    return router
