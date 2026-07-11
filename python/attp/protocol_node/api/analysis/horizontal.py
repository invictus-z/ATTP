"""横向分析 API 路由 — Cross-Session / DID 级全局行为分析。

端点（prefix `/api/analysis/h`）：
    POST /api/analysis/h/trigger/{did}     — 手动触发横向分析
    GET  /api/analysis/h/report/{did}      — 获取DID全部横向分析报告
    GET  /api/analysis/h/state/{did}       — 获取DID横向累积状态（含已生成报告数）
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
    router = APIRouter(prefix="/api/analysis/h")
    _coord_ref = coordinator_holder

    @router.post("/trigger/{did}")
    async def trigger_horizontal(did: str):
        """手动触发DID横向分析（异步，立即返回）。"""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"triggered": False, "reason": "analysis_disabled"}
        return await _coordinator.trigger_horizontal_async(did)

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
        """获取DID横向分析累积状态（batch_index 即已生成报告批次/次数）。"""
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
                "accumulated_count": state.get("accumulated_count", 0), # 当前未分析行为的数量
                "last_trace_id": state.get("last_trace_id", 0), # 已分析的最新位置
                "batch_index": state.get("batch_index", 0), # 已生成的报告总数
                "node_type": state.get("node_type", ""),
                "has_context": bool(state.get("context")),
            }
        except Exception as e:
            logger.error("Error loading horizontal state for {}: {}", did, e)
            return {"did": did, "accumulated_count": 0, "error": str(e)}

    return router
