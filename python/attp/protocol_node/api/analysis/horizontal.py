"""横向分析 API 路由 — Cross-Session / DID 级全局行为分析。

端点：
    POST /api/analysis/horizontal/trigger/{did}   — 手动触发横向分析
    GET  /api/analysis/horizontal/status/{did}     — 查询横向分析任务状态
    GET  /api/analysis/horizontal/report/{did}     — 获取DID全部横向分析报告
    GET  /api/analysis/horizontal/state/{did}      — 获取DID横向累积状态
    GET  /api/analysis/cross-lock/{session_id}     — 十字锁定综合视图
"""

import json

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer
from attp.protocol_node.api.malicious import _normalise_did

logger = get_logger("HorizontalAPI")


def get_horizontal_analysis_router(
    tracer: ProtocolTracer,
    coordinator_holder: list,
) -> APIRouter:
    router = APIRouter(prefix="/api/analysis/horizontal")
    _coord_ref = coordinator_holder

    @router.post("/trigger/{did}")
    async def trigger_horizontal(did: str):
        """手动触发DID横向分析（异步，立即返回）。"""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"triggered": False, "reason": "analysis_disabled"}
        return await _coordinator.trigger_horizontal_async(did)

    @router.get("/status/{did}")
    async def get_horizontal_status(did: str):
        """查询横向分析任务状态。"""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"status": "not_found", "did": did}
        return _coordinator.get_horizontal_status(did)

    @router.get("/report/{did}")
    async def get_horizontal_reports(did: str):
        """获取DID全部横向分析报告。"""
        canonical = _normalise_did(did)
        try:
            reports = await tracer.storage.recover_horizontal_reports(canonical)
            parsed = []
            for r in reports:
                parsed.append({
                    "id": r["id"],
                    "batch_index": r["batch_index"],
                    "from_trace_id": r["from_trace_id"],
                    "to_trace_id": r["to_trace_id"],
                    "sessions_scanned": r.get("sessions_scanned", 0),
                    "timestamp": r.get("timestamp"),
                    "report": json.loads(r["report_json"]) if r.get("report_json") else {},
                })
            return {
                "did": canonical,
                "reports": parsed,
                "total_batches": len(parsed),
            }
        except Exception as e:
            logger.error("Error recovering horizontal reports for {}: {}", did, e)
            return {"did": did, "reports": [], "total_batches": 0}

    @router.get("/state/{did}")
    async def get_horizontal_state(did: str):
        """获取DID横向分析累积状态。"""
        canonical = _normalise_did(did)
        try:
            state = await tracer.storage.load_horizontal_state(canonical)
            if not state:
                return {
                    "did": canonical,
                    "accumulated_count": 0,
                    "last_trace_id": 0,
                    "batch_index": 0,
                    "has_context": False,
                }
            return {
                "did": canonical,
                "accumulated_count": state.get("accumulated_count", 0),
                "last_trace_id": state.get("last_trace_id", 0),
                "batch_index": state.get("batch_index", 0),
                "node_type": state.get("node_type", ""),
                "has_context": bool(state.get("context")),
            }
        except Exception as e:
            logger.error("Error loading horizontal state for {}: {}", did, e)
            return {"did": did, "accumulated_count": 0, "error": str(e)}

    # ------------------------------------------------------------------
    # 十字锁定综合视图
    # ------------------------------------------------------------------

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
                    "accumulated_count": h_state.get("accumulated_count", 0) if h_state else 0,
                    "last_horizontal_analysis": latest_h_report,
                })
            except Exception as e:
                logger.error("Error loading horizontal data for did={}: {}", did, e)
                horizontal_dids.append({"did": did, "accumulated_count": 0, "last_horizontal_analysis": None})

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
