"""十字锁定（Cross-Lock）综合视图 API 路由 — 纵向 + 横向综合分析。

端点（prefix `/api/analysis`）：
    GET  /api/analysis/cross-lock/{session_id}  — 纵向 + 横向综合视图
"""

import json

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("CrossLockAPI")


def get_cross_lock_router(tracer: ProtocolTracer) -> APIRouter:
    router = APIRouter(prefix="/api/analysis")

    @router.get("/cross-lock/{session_id}")
    async def get_cross_lock_view(session_id: str, protocol_node_address: str | None = None):
        """返回纵向 + 横向综合分析视图。"""
        # 1. Fetch behavior traces
        try:
            trace_entries = await tracer.recover_behavior_trace(session_id, protocol_node_address)
        except Exception as e:
            logger.error("Error recovering traces for cross-lock {}: {}", session_id, e)
            trace_entries = []

        # 2. Fetch vertical analysis reports
        try:
            report_rows = await tracer.recover_analysis_reports(session_id)
        except Exception as e:
            logger.error("Error recovering reports for cross-lock {}: {}", session_id, e)
            report_rows = []

        # 3. Parse vertical reports and extract alerts
        parsed_reports = []
        vertical_alerts = []
        for r in report_rows:
            report_data = json.loads(r["report_json"]) if r.get("report_json") else {}
            parsed_reports.append({
                "id": r["id"],
                "batch_index": r["batch_index"],
                "from_trace_id": r["from_trace_id"],
                "to_trace_id": r["to_trace_id"],
                "timestamp": r.get("timestamp"),
                "report": report_data,
            })
            if report_data.get("overall_verdict") in ("suspicious", "malicious"):
                vertical_alerts.append({
                    "report_id": r["id"],
                    "batch_index": r["batch_index"],
                    "verdict": report_data.get("overall_verdict"),
                    "summary": report_data.get("summary", ""),
                })

        # 4. Extract unique DIDs and fetch horizontal state
        unique_dids = list({t.get("node_did", "") for t in trace_entries if t.get("node_did")})
        horizontal_dids = []
        for did in unique_dids:
            try:
                h_state = await tracer.storage.load_horizontal_state(did)
                h_reports = await tracer.storage.recover_horizontal_reports(did)
                latest_h_report = None
                if h_reports:
                    latest = h_reports[-1]
                    try:
                        report_data = json.loads(latest.get("report_json") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        report_data = {}
                    latest_h_report = {
                        "batch_index": latest.get("batch_index", 0),
                        "verdict": report_data.get("overall_verdict"),
                        "timestamp": latest.get("timestamp"),
                    }
                horizontal_dids.append({
                    "did": did,
                    "pending_count": h_state.get("pending_count", 0) if h_state else 0,
                    "last_horizontal_analysis": latest_h_report,
                })
            except Exception as e:
                logger.error("Error loading horizontal data for did={}: {}", did, e)
                horizontal_dids.append({"did": did, "pending_count": 0, "last_horizontal_analysis": None})

        return {
            "session_id": session_id,
            "vertical": {
                "traces": len(trace_entries),
                "reports": parsed_reports,
                "total_batches": len(parsed_reports),
                "alerts": vertical_alerts,
            },
            "horizontal": {
                "tracked_dids": horizontal_dids,
            },
        }

    return router
