"""十字锁定（Cross-Lock）综合视图 API 路由 — 纵向逐跳 + 横向 F/确认。

端点（prefix `/api/analysis`）：
    GET  /api/analysis/cross-lock/{session_id}  — 纵向 hop_scores + 各 DID 横向 F/volume
"""

import json

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.analysis.base_models import overall_verdict_for_severities
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("CrossLockAPI")


def get_cross_lock_router(tracer: ProtocolTracer) -> APIRouter:
    router = APIRouter(prefix="/api/analysis")

    @router.get("/cross-lock/{session_id}")
    async def get_cross_lock_view(session_id: str, protocol_node_address: str | None = None):
        """返回纵向逐跳评分 + 涉及各 DID 的横向 F/volume/最近确认。"""
        # 1. traces（用于提取涉及 DID）
        try:
            trace_entries = await tracer.recover_behavior_trace(session_id, protocol_node_address)
        except Exception as e:
            logger.error("Error recovering traces for cross-lock {}: {}", session_id, e)
            trace_entries = []

        # 2. hop scores（纵向逐跳）
        try:
            hop_scores = await tracer.query_hop_scores_by_session(session_id)
        except Exception as e:
            logger.error("Error recovering hop scores for cross-lock {}: {}", session_id, e)
            hop_scores = []
        severities = [h.get("severity", "none") for h in hop_scores]

        # 3. R_T 告警
        try:
            vertical_alerts = await tracer.query_malicious_reports(
                session_id=session_id, source="vertical_analysis",
            )
        except Exception:
            vertical_alerts = []

        # 4. 各 DID 横向 F/volume/最近确认
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
                        "confirmed": report_data.get("confirmed", False),
                        "overall_verdict": report_data.get("overall_verdict"),
                        "timestamp": latest.get("timestamp"),
                    }
                horizontal_dids.append({
                    "did": did,
                    "f_value": h_state.get("f_value", 0.0) if h_state else 0.0,
                    "volume": h_state.get("volume", 0) if h_state else 0,
                    "batch_index": h_state.get("batch_index", 0) if h_state else 0,
                    "last_horizontal_analysis": latest_h_report,
                })
            except Exception as e:
                logger.error("Error loading horizontal data for did={}: {}", did, e)
                horizontal_dids.append({
                    "did": did, "f_value": 0.0, "volume": 0,
                    "last_horizontal_analysis": None,
                })

        return {
            "session_id": session_id,
            "vertical": {
                "traces": len(trace_entries),
                "hop_scores": hop_scores,
                "overall_verdict": overall_verdict_for_severities(severities),
                "total_hops": len(hop_scores),
                "alerts": vertical_alerts,
            },
            "horizontal": {
                "tracked_dids": horizontal_dids,
            },
        }

    return router
