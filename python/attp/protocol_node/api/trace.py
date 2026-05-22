"""协议相关 API 路由 — 行为溯源、分析报告、污点审计。

迁移自 attp/app/web/api/trace.py，origin_did → protocol_node_address。
"""

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter

from attp.app.logging import get_logger
from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("Tracing")

_SENDER_TYPE_MAP = {"A": "agent", "U": "user", "T": "tool"}


def get_behavior_router(
    tracer: ProtocolTracer,
    session_manager: Any = None,
    orchestrator: Any = None,
    orchestrator_holder: list | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api")
    # 统一 late-binding：优先使用 orchestrator_holder
    _orch_ref = orchestrator_holder if orchestrator_holder is not None else [orchestrator]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    @router.get("/status")
    async def get_status():
        """Health check endpoint for protocol node connectivity detection."""
        return {
            "status": "ok",
            "service": "protocol_node",
        }

    @router.get("/behavior/{session_id}")
    async def get_behavior_trace(session_id: str, protocol_node_address: str | None = None):
        """Return full behavior trace as a flat chain ordered by hop_count."""
        try:
            entries = await tracer.recover_behavior_trace(session_id, protocol_node_address)

            chain = []
            for row in entries:
                ft = row["field_type"]
                chain.append({
                    "hop_count": row["hop_count"],
                    "field_type": ft,
                    "sender_type": _SENDER_TYPE_MAP.get(ft[0], "unknown"),
                    "sender_did": row["sender_did"],
                    "target_did": row.get("target_did", ""),
                    "content": row.get("content", ""),
                    "timestamp": row.get("timestamp"),
                })

            return {
                "session_id": session_id,
                "protocol_node_address": protocol_node_address,
                "chain": chain,
            }
        except Exception as e:
            logger.error("Error recovering behavior trace for {}: {}", session_id, e)
            return {
                "session_id": session_id,
                "protocol_node_address": protocol_node_address,
                "chain": [],
            }

    @router.get("/analysis/{session_id}")
    async def get_analysis_reports(session_id: str):
        """Return all semantic taint analysis reports for a session."""
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
    # Intent & analysis state
    # ------------------------------------------------------------------

    @router.get("/analysis/intent/{session_id}")
    async def get_analysis_intent(session_id: str):
        """Return the extracted intent and analysis state for a session."""
        if not session_manager:
            return {
                "session_id": session_id,
                "intent": None,
                "analysis_state": None,
            }

        session = session_manager.get(session_id)
        if not session:
            return {
                "session_id": session_id,
                "intent": None,
                "analysis_state": None,
            }

        intent_data = session.get_intent()
        state = session.get_analysis_state()

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
    # Aggregation (traces + reports + alerts)
    # ------------------------------------------------------------------

    @router.get("/analysis/aggregate/{session_id}")
    async def get_aggregate_analysis(session_id: str, protocol_node_address: str | None = None):
        """Return behavior traces + analysis reports + alerts combined."""
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

        # 3. Build flat trace chain (include DB id for evidence linking)
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

        # 5. Get intent if available
        intent = None
        if session_manager:
            session = session_manager.get(session_id)
            if session:
                intent = session.get_intent()

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
    # Manual analysis trigger
    # ------------------------------------------------------------------

    @router.post("/analysis/trigger/{session_id}")
    async def trigger_analysis(session_id: str):
        """Manually trigger taint analysis (async, returns immediately)."""
        _orch = _orch_ref[0]
        if not _orch:
            return {"triggered": False, "reason": "analysis_disabled"}
        return await _orch.trigger_analysis_async(session_id)

    @router.get("/analysis/status/{session_id}")
    async def get_analysis_status(session_id: str):
        """Query async analysis task status and phase."""
        _orch = _orch_ref[0]
        if not _orch:
            return {"status": "not_found", "session_id": session_id}
        return _orch.get_analysis_status(session_id)

    return router
