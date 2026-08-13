"""横向分析 API 路由 — Cross-Session / DID 级 F 累加 + 确认（逐跳改版）。

端点（prefix `/api/analysis/h`）：
    POST /api/analysis/h/trigger/{did}      — 手动触发横轴确认
    GET  /api/analysis/h/report/{did}       — DID 全部确认报告
    GET  /api/analysis/h/state/{did}        — F / volume / 游标 / 批次
    GET  /api/analysis/h/llm-status/{did}   — 确认任务状态（供轮询）
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
        """手动触发 DID 横轴确认（异步，立即返回）。"""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"triggered": False, "reason": "analysis_disabled"}
        return await _coordinator.trigger_horizontal_async(_normalise_did(did))

    @router.get("/report/{did}")
    async def get_horizontal_reports(did: str):
        """获取 DID 全部横轴确认报告。"""
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
            return {"did": canonical, "reports": parsed, "total_batches": len(parsed)}
        except Exception as e:
            logger.error("Error recovering horizontal reports for {}: {}", did, e)
            return {"did": did, "reports": [], "total_batches": 0}

    @router.get("/state/{did}")
    async def get_horizontal_state(did: str):
        """获取 DID 横向累积状态：F / 未分析数 / 游标 / 批次 / R_S。"""
        canonical = _normalise_did(did)
        # R_S 来自协调器（横轴阈值，使前端 F 进度条分母与后端一致；横轴未启用时为 None）。
        _coordinator = _coord_ref[0]
        r_s = _coordinator.r_s if _coordinator else None
        try:
            state = await tracer.storage.load_horizontal_state(canonical)
            last_trace_id = state.get("last_trace_id", 0) if state else 0
            # 未分析数 = 该节点在确认游标之后的全部跳数（最后一次分析位置 → 最新位置）。
            unanalyzed = await tracer.storage.count_traces_by_did_since(canonical, last_trace_id)
            if not state:
                return {
                    "did": canonical,
                    "f_value": 0.0, "volume": 0,
                    "unanalyzed_count": unanalyzed,
                    "last_trace_id": 0, "batch_index": 0,
                    "node_type": "", "has_context": False,
                    "r_s": r_s,
                }
            return {
                "did": canonical,
                "f_value": state.get("f_value", 0.0),       # 累积偏离 F_d = Σ s_j³
                "volume": state.get("volume", 0),            # 自上次闭案以来喂入 F 的跳数
                "unanalyzed_count": unanalyzed,              # 游标之后该节点全部未分析跳数
                "last_trace_id": last_trace_id,              # 确认游标
                "batch_index": state.get("batch_index", 0),  # 已完成确认次数
                "node_type": state.get("node_type", ""),
                "has_context": bool(state.get("context")),
                "r_s": r_s,
            }
        except Exception as e:
            logger.error("Error loading horizontal state for {}: {}", did, e)
            return {"did": did, "f_value": 0.0, "r_s": r_s, "error": str(e)}

    @router.get("/llm-status/{did}")
    async def get_llm_status(did: str):
        """查询横轴确认任务状态（供前端轮询）。"""
        _coordinator = _coord_ref[0]
        canonical = _normalise_did(did)
        if not _coordinator:
            return {"status": "disabled", "did": canonical}
        return _coordinator.get_horizontal_status(canonical)

    return router
