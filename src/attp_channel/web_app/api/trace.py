from datetime import datetime
from fastapi import APIRouter
from loguru import logger
from attp_channel.tracing import tracer


def get_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/traces/{session_id}")
    async def get_session_trace(session_id: str):
        try:
            rows = tracer.recover_trace(session_id)
            rows.reverse()
            path_list = []
            for row in rows:
                try:
                    ts = datetime.fromtimestamp(row["timestamp"])
                    time_iso = ts.isoformat() + "Z"
                except Exception:
                    time_iso = str(row["timestamp"])
                log_entry = {
                    "node_did": row["node_did"],
                    "target_did": row.get("target_did"),
                    "Entry_Hash": row["entry_hash"],
                    "Prev_Hash": row["prev_hash"],
                    "Session_ID": row["session_id"],
                    "Hop_Count": row["hop_count"],
                    "Content_Snapshot": row["content_snapshot"],
                    "Signature": row["signature"],
                    "Timestamp": time_iso,
                }
                if row["hop_count"] == 0:
                    log_entry["Genesis_Hash"] = row["entry_hash"]
                path_list.append({"Log": log_entry})
            return {
                "Session_ID": session_id,
                "Intent_Tag": "Interaction_Trace",
                "Path": path_list,
            }
        except Exception as e:
            logger.error(f"Error recovering trace for {session_id}: {e}")
            return {
                "Session_ID": session_id,
                "Intent_Tag": "Error",
                "Path": [],
            }

    return router