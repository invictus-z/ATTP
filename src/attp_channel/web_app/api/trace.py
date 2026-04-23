from datetime import datetime
from fastapi import APIRouter

from attp_channel.logging import get_logger
from attp_channel.protocol import tracer

logger = get_logger("Tracing")


def get_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/traces/{session_id}")
    async def get_session_trace(session_id: str):
        try:
            rows = tracer.recover_trace(session_id)
            rows.reverse()
            path_list = []
            origin_did = None
            genesis_signature = None
            for row in rows:
                try:
                    ts = datetime.fromtimestamp(row["timestamp"])
                    time_iso = ts.isoformat() + "Z"
                except Exception:
                    time_iso = str(row["timestamp"])

                if row["hop_count"] == 0:
                    origin_did = row.get("origin_did")
                    genesis_signature = row.get("genesis_signature")

                log_entry = {
                    "node_did": row["node_did"],
                    "target_did": row.get("target_did"),
                    "Session_ID": row["session_id"],
                    "Hop_Count": row["hop_count"],
                    "Signature": row["signature"],
                    "Timestamp": time_iso,
                    "Content": row.get("content", ""),
                }
                path_list.append({"Log": log_entry})
            return {
                "Session_ID": session_id,
                "Origin_DID": origin_did,
                "Genesis_Signature": genesis_signature,
                "Intent_Tag": "Interaction_Trace",
                "Path": path_list,
            }
        except Exception as e:
            logger.error("Error recovering trace for {}: {}", session_id, e)
            return {
                "Session_ID": session_id,
                "Intent_Tag": "Error",
                "Path": [],
            }

    return router
