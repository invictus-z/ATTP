"""纵向分析 API 路由 — Session 级语义污点分析。

端点：
    GET  /api/analysis/{session_id}           — 获取纵向分析报告
    GET  /api/analysis/intent/{session_id}     — 获取意图与分析状态
    GET  /api/analysis/aggregate/{session_id}  — 聚合视图（traces + reports + alerts）
    POST /api/analysis/trigger/{session_id}    — 手动触发纵向分析
    GET  /api/analysis/status/{session_id}     — 查询纵向分析任务状态
"""

import json
from typing import Any

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("VerticalAPI")

_SENDER_TYPE_MAP = {"A": "agent", "U": "user", "T": "tool"}


def get_vertical_analysis_router(
    tracer: ProtocolTracer,
    session_manager: Any = None,
    coordinator_holder: list | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    _coord_ref = coordinator_holder if coordinator_holder is not None else [None]

    # ------------------------------------------------------------------
    # 分析报告查询
    # ------------------------------------------------------------------

    @router.get("/analysis/{session_id}")
    async def get_analysis_reports(session_id: str):
        """Return all vertical taint analysis reports for a session."""
        try:
            reports = await tracer.recover_analysis_reports(session_id)
            parsed = []
            for r in reports:
                parsed.append({
                    "id": r["id"],
                    "batch_index": r["batch_index"],
                    "from_trace_id": r["from_trace_id"],
                    "to_trace_id": r["to_trace_id"],
                    "timestamp": r.get("timestamp"),
                    "report": json.loads(r["report_json"]) if r.get("report_json") else {},
                })
            return {
                "session_id": session_id,
                "reports": parsed,
                "total_batches": len(parsed),
            }
        except Exception as e:
            logger.error("Error recovering analysis reports for {}: {}", session_id, e)
            return {
                "session_id": session_id,
                "reports": [],
                "total_batches": 0,
            }

    # ------------------------------------------------------------------
    # Intent & 分析状态
    # ------------------------------------------------------------------

    @router.get("/analysis/intent/{session_id}")
    async def get_analysis_intent(session_id: str):
        """Return the extracted intent and vertical analysis state for a session.

        Priority: in-memory session → fallback to vertical_analysis_states DB table.
        """
        intent_data = None
        state: dict[str, Any] = {}

        # 1. 尝试从内存中的 session 获取
        if session_manager:
            session = session_manager.get(session_id)
            if session:
                intent_data = session.get_intent()
                state = session.get_analysis_state() or {}

        # 2. 内存未命中 → fallback 到 DB
        if intent_data is None and not state.get("last_trace_id"):
            try:
                saved = await tracer.load_analysis_session(session_id)
                if saved:
                    if saved.get("intent_json"):
                        intent_data = json.loads(saved["intent_json"])
                    state = {
                        "batch_index": saved.get("batch_index", 0),
                        "last_trace_id": saved.get("last_trace_id", 0),
                        "report_count": saved.get("report_count", 0),
                        "context": saved.get("context", ""),
                    }
            except Exception as e:
                logger.error("Error loading analysis session for {}: {}", session_id, e)

        return {
            "session_id": session_id,
            "intent": intent_data,
            "analysis_state": {
                "batch_index": state.get("batch_index", 0),
                "last_trace_id": state.get("last_trace_id", 0),
                "report_count": state.get("report_count", 0),
                "has_context": bool(state.get("context")),
            },
        }

    # ------------------------------------------------------------------
    # 聚合视图（traces + reports + alerts）
    # ------------------------------------------------------------------

    @router.get("/analysis/aggregate/{session_id}")
    async def get_aggregate_analysis(session_id: str, protocol_node_address: str | None = None):
        """Return behavior traces + vertical analysis reports + alerts combined."""
        # 1. Fetch behavior traces
        try:
            trace_entries = await tracer.recover_behavior_trace(session_id, protocol_node_address)
        except Exception as e:
            logger.error("Error recovering traces for aggregate {}: {}", session_id, e)
            trace_entries = []

        # 2. Fetch analysis reports
        try:
            report_rows = await tracer.recover_analysis_reports(session_id)
        except Exception as e:
            logger.error("Error recovering reports for aggregate {}: {}", session_id, e)
            report_rows = []

        # 3. Build flat trace chain
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

        # 4. Parse reports and extract alerts
        parsed_reports = []
        alerts = []
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
                alerts.append({
                    "report_id": r["id"],
                    "batch_index": r["batch_index"],
                    "verdict": report_data.get("overall_verdict"),
                    "summary": report_data.get("summary", ""),
                    "from_trace_id": r["from_trace_id"],
                    "to_trace_id": r["to_trace_id"],
                    "timestamp": r.get("timestamp"),
                    "suspicious_nodes": [
                        {
                            "node_did": v.get("node_did"),
                            "severity": v.get("severity"),
                            "taint_score": v.get("taint_score"),
                            "evidence": v.get("evidence"),
                        }
                        for v in report_data.get("node_verdicts", [])
                        if v.get("severity") in ("medium", "high")
                    ],
                })

        # 5. Get intent (in-memory first, fallback to DB)
        intent = None
        if session_manager:
            session = session_manager.get(session_id)
            if session:
                intent = session.get_intent()
        if intent is None:
            try:
                saved = await tracer.load_analysis_session(session_id)
                if saved and saved.get("intent_json"):
                    intent = json.loads(saved["intent_json"])
            except Exception:
                pass

        return {
            "session_id": session_id,
            "intent": intent,
            "traces": {
                "chain": chain,
                "total_entries": len(trace_entries),
            },
            "reports": parsed_reports,
            "alerts": alerts,
            "total_batches": len(parsed_reports),
            "total_alerts": len(alerts),
        }

    # ------------------------------------------------------------------
    # 手动触发纵向分析
    # ------------------------------------------------------------------

    @router.post("/analysis/trigger/{session_id}")
    async def trigger_analysis(session_id: str):
        """Manually trigger vertical taint analysis (async, returns immediately)."""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"triggered": False, "reason": "analysis_disabled"}
        return await _coordinator.trigger_analysis_async(session_id)

    @router.get("/analysis/status/{session_id}")
    async def get_analysis_status(session_id: str):
        """Query async vertical analysis task status and phase."""
        _coordinator = _coord_ref[0]
        if not _coordinator:
            return {"status": "not_found", "session_id": session_id}
        return _coordinator.get_analysis_status(session_id)

    return router
