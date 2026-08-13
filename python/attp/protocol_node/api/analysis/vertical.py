"""纵向分析 API 路由 — Session 级逐跳评分（逐跳改版）。

端点（prefix `/api/analysis/v`）：
    GET  /api/analysis/v/report/{session_id}      — 会话逐跳评分聚合报告
    GET  /api/analysis/v/state/{session_id}       — 意图流 / 隐状态 / 打分游标
    GET  /api/analysis/v/aggregate/{session_id}   — traces + hop_scores + R_T 告警
    POST /api/analysis/v/trigger/{session_id}     — 手动触发（补打未评分跳）
    GET  /api/analysis/v/llm-status/{session_id}  — worker 状态（供轮询）
"""

import json
from typing import Any

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.analysis.base_models import overall_verdict_for_severities
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("VerticalAPI")

_SENDER_TYPE_MAP = {"A": "agent", "U": "user", "T": "tool"}


async def _astate(tracer: ProtocolTracer, session_id: str) -> dict[str, Any]:
    """异步读取纵向状态（intent_revisions / hidden_state / cursor / initiator）。"""
    saved = await tracer.load_vertical_state(session_id)
    if not saved:
        return {
            "initiator_did": "", "intent_revisions": [],
            "hidden_state": "", "last_scored_trace_id": 0,
        }
    try:
        revisions = json.loads(saved.get("intent_revisions_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        revisions = []
    return {
        "initiator_did": saved.get("initiator_did", ""),
        "intent_revisions": revisions,
        "hidden_state": saved.get("hidden_state", ""),
        "last_scored_trace_id": saved.get("last_scored_trace_id", 0),
    }


def get_vertical_analysis_router(
    tracer: ProtocolTracer,
    session_manager: Any = None,
    coordinator_holder: list | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/analysis/v")
    _coord_ref = coordinator_holder if coordinator_holder is not None else [None]

    # ------------------------------------------------------------------
    # 逐跳评分聚合报告
    # ------------------------------------------------------------------

    @router.get("/report/{session_id}")
    async def get_hop_scores(session_id: str):
        """会话内逐跳评分聚合（overall_verdict 由代码推导）。"""
        try:
            hop_scores = await tracer.query_hop_scores_by_session(session_id)
            state = await _astate(tracer, session_id)
            severities = [h.get("severity", "none") for h in hop_scores]
            max_score = max((h.get("score", 0.0) for h in hop_scores), default=0.0)
            return {
                "session_id": session_id,
                "initiator_did": state["initiator_did"],
                "intent_revisions": state["intent_revisions"],
                "hidden_state": state["hidden_state"],
                "hop_scores": hop_scores,
                "overall_verdict": overall_verdict_for_severities(severities),
                "max_score": max_score,
                "total_hops": len(hop_scores),
                "last_scored_trace_id": state["last_scored_trace_id"],
            }
        except Exception as e:
            logger.error("Error recovering hop scores for {}: {}", session_id, e)
            return {"session_id": session_id, "hop_scores": [], "total_hops": 0}

    # ------------------------------------------------------------------
    # 意图流与状态
    # ------------------------------------------------------------------

    @router.get("/state/{session_id}")
    async def get_vertical_state(session_id: str):
        """意图流 + 隐状态 + 打分游标 + 发起者 DID。"""
        state = await _astate(tracer, session_id)
        return {
            "session_id": session_id,
            "initiator_did": state["initiator_did"],
            "intent_revisions": state["intent_revisions"],
            "has_hidden_state": bool(state["hidden_state"]),
            "last_scored_trace_id": state["last_scored_trace_id"],
            "intent_revision_count": len(state["intent_revisions"]),
        }

    # ------------------------------------------------------------------
    # 聚合视图（traces + hop_scores + R_T 告警）
    # ------------------------------------------------------------------

    @router.get("/aggregate/{session_id}")
    async def get_aggregate_analysis(session_id: str, protocol_node_address: str | None = None):
        """行为链 + 逐跳评分 + R_T 告警。"""
        # 1. traces
        try:
            trace_entries = await tracer.recover_behavior_trace(session_id, protocol_node_address)
        except Exception as e:
            logger.error("Error recovering traces for aggregate {}: {}", session_id, e)
            trace_entries = []

        chain = []
        for row in trace_entries:
            ft = row["field_type"]
            chain.append({
                "id": row.get("id"),
                "hop_count": row["hop_count"],
                "field_type": ft,
                "sender_type": _SENDER_TYPE_MAP.get(ft[0], "unknown"),
                "sender_did": row["sender_did"],
                "target_did": row.get("target_did", ""),
                "content": row.get("content", ""),
                "timestamp": row.get("timestamp"),
            })

        # 2. hop scores
        try:
            hop_scores = await tracer.query_hop_scores_by_session(session_id)
        except Exception as e:
            logger.error("Error recovering hop scores for aggregate {}: {}", session_id, e)
            hop_scores = []

        # 3. R_T 告警（source=vertical_analysis）
        try:
            alerts = await tracer.query_malicious_reports(
                session_id=session_id, source="vertical_analysis",
            )
        except Exception as e:
            logger.error("Error recovering alerts for aggregate {}: {}", session_id, e)
            alerts = []

        severities = [h.get("severity", "none") for h in hop_scores]
        return {
            "session_id": session_id,
            "traces": {"chain": chain, "total_entries": len(trace_entries)},
            "hop_scores": hop_scores,
            "overall_verdict": overall_verdict_for_severities(severities),
            "alerts": alerts,
            "total_hops": len(hop_scores),
            "total_alerts": len(alerts),
        }

    # ------------------------------------------------------------------
    # 手动触发 + worker 状态
    # ------------------------------------------------------------------

    @router.post("/trigger/{session_id}")
    async def trigger_analysis(session_id: str):
        """手动触发：补打该会话未评分的跳。"""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"triggered": False, "reason": "analysis_disabled"}
        return await _coordinator.trigger_analysis_async(session_id)

    @router.get("/llm-status/{session_id}")
    async def get_llm_status(session_id: str):
        """查询纵轴 worker 阶段（供前端轮询）。"""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"status": "disabled", "session_id": session_id}
        return _coordinator.get_analysis_status(session_id)

    return router
