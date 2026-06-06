"""Vertical Axis — 纵向分析编排器。

协调意图提取、纵向分析调度、横向累积触发。
分析完成后提取 analyzed_dids，调用横向触发回调。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Awaitable

from attp.app.logging import get_logger
from attp.core.analysis.base_models import IntentDescriptor
from attp.core.analysis.vertical.models import VerticalTaintReport

if TYPE_CHECKING:
    from attp.core.analysis.vertical.analyzer import VerticalTaintAnalyzer
    from attp.core.sessions.protocol_node.management.vertical_state import VerticalAnalysisManager
    from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("VerticalAnalysis")


@dataclass
class VerticalAnalysisResult:
    """Result of a vertical analysis run."""

    triggered: bool
    reason: str = ""
    report: VerticalTaintReport | None = None

    def to_dict(self) -> dict:
        d: dict = {"triggered": self.triggered, "reason": self.reason}
        if self.report:
            d["report"] = self.report.to_dict()
        return d


class VerticalOrchestrator:
    """Coordinates intent extraction, batch counting, and vertical analysis scheduling.

    Entirely driven by DataPort record reception — no dependency on web layer.
    Analysis state is persisted to SQLite via VerticalAnalysisManager for crash recovery.

    Cross-Lock integration:
        After each vertical analysis, calls ``horizontal_trigger_callback(did, session_id)``
        for every DID involved in the analysis, enabling the horizontal axis to accumulate.
    """

    def __init__(
        self,
        analyzer: VerticalTaintAnalyzer,
        vertical_state_mgr: VerticalAnalysisManager,
        tracer: ProtocolTracer,
        batch_size: int = 10,
        horizontal_trigger_callback: Callable[[str, str], Awaitable[None]] | None = None,
    ):
        self._analyzer = analyzer
        self._state_mgr = vertical_state_mgr
        self._tracer = tracer
        self._batch_size = batch_size
        self._horizontal_trigger_callback = horizontal_trigger_callback
        self._locks: dict[str, asyncio.Lock] = {}
        self._restored_sessions: set[str] = set()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_results: dict[str, VerticalAnalysisResult] = {}
        self._task_phases: dict[str, str] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    # ------------------------------------------------------------------
    # Callbacks (wired into DataPort)
    # ------------------------------------------------------------------

    async def on_field_U2A_recorded(self, session_id: str, content: str) -> None:
        """Called when a User→Agent message (U2A) is recorded.

        Extracts intent from the first user message of a session.
        Caches content for retry on subsequent triggers if extraction fails.
        """
        await self._state_mgr.restore_state(session_id)

        intent = await self._state_mgr.get_intent(session_id)
        if intent:
            return

        extracted = await self._analyzer.extract_intent(content)
        if extracted:
            await self._state_mgr.set_intent(session_id, extracted.to_dict())
            logger.info("Intent extracted for session={}", session_id)
        else:
            logger.warning(
                "Intent extraction failed for session={}, will retry on next trigger",
                session_id,
            )

    async def on_record_received(self, session_id: str) -> None:
        """Called by DataPort when a record message is received.

        Increments report counter and triggers analysis if batch size reached.
        """
        async with self._get_lock(session_id):
            count = await self._state_mgr.increment_report_count(session_id)

            if count >= self._batch_size:
                logger.info(
                    "Vertical batch size reached ({}/{}), triggering analysis for session={}",
                    count, self._batch_size, session_id,
                )
                await self.run_analysis(session_id, is_final=False)

    # ------------------------------------------------------------------
    # Core analysis runner
    # ------------------------------------------------------------------

    async def run_analysis(self, session_id: str, is_final: bool = False) -> VerticalAnalysisResult:
        """Run vertical semantic taint analysis for a session.

        IMPORTANT: Caller must hold the per-session lock.
        """
        state = await self._state_mgr.get_state(session_id)
        intent_data = state.get("intent")

        if not intent_data:
            logger.warning(
                "Cannot run vertical analysis for session={}: no intent extracted",
                session_id,
            )
            return VerticalAnalysisResult(triggered=False, reason="no_intent")

        intent = IntentDescriptor.from_dict(intent_data)

        # Recover unchecked traces
        self._task_phases[session_id] = "recovering_traces"
        last_id = state["last_trace_id"]
        traces, max_id = await self._tracer.recover_traces_since(session_id, last_id)

        if not traces:
            await self._state_mgr.reset_report_count(session_id)
            return VerticalAnalysisResult(triggered=False, reason="no_unanalyzed_traces")

        batch_index = state["batch_index"] + 1
        previous_context = state["context"]

        logger.info(
            "Running vertical analysis: session={}, batch={}, traces={}, is_final={}",
            session_id, batch_index, len(traces), is_final,
        )

        self._task_phases[session_id] = "analyzing"
        report = await self._analyzer.analyze(
            session_id=session_id,
            batch_index=batch_index,
            from_trace_id=last_id,
            to_trace_id=max_id,
            traces=traces,
            intent=intent,
            previous_context=previous_context,
        )

        # Persist report
        self._task_phases[session_id] = "saving_results"
        report_json = json.dumps(report.to_dict(), ensure_ascii=False)
        await self._tracer.save_analysis_report(report_json)

        # Update session state
        await self._state_mgr.reset_report_count(session_id)
        await self._state_mgr.update_cursor(
            session_id, batch_index=batch_index,
            last_trace_id=max_id, context=report.context_summary,
        )

        # Notify if suspicious or malicious
        if report.overall_verdict == "error":
            logger.error("Vertical analysis error for session={}: {}", session_id, report.summary)
        elif report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(session_id, report)

        # Cross-Lock: trigger horizontal accumulation for each involved DID
        if self._horizontal_trigger_callback and report.analyzed_dids:
            for did in report.analyzed_dids:
                try:
                    await self._horizontal_trigger_callback(did, session_id)
                except Exception as e:
                    logger.error(
                        "Horizontal trigger callback failed for did={}, session={}: {}",
                        did, session_id, e,
                    )

        logger.info(
            "Vertical analysis complete: session={}, verdict={}, nodes_checked={}",
            session_id, report.overall_verdict, len(report.node_verdicts),
        )
        return VerticalAnalysisResult(triggered=True, report=report)

    # ------------------------------------------------------------------
    # Async task management (for manual trigger endpoint)
    # ------------------------------------------------------------------

    async def trigger_analysis_async(self, session_id: str) -> dict:
        """Fire-and-forget analysis task. Returns immediately with status."""
        if session_id in self._running_tasks:
            return {"triggered": True, "status": "already_running", "session_id": session_id}

        async def _task_body():
            try:
                async with self._get_lock(session_id):
                    result = await self.run_analysis(session_id, is_final=False)
                return result
            except Exception as e:
                logger.error("Async vertical analysis task failed for session={}: {}", session_id, e)
                return VerticalAnalysisResult(triggered=False, reason=f"task_error: {e}")

        task = asyncio.create_task(_task_body())
        self._running_tasks[session_id] = task
        self._task_phases[session_id] = "starting"

        def _on_done(t: asyncio.Task):
            self._task_results[session_id] = t.result()
            self._running_tasks.pop(session_id, None)
            self._task_phases.pop(session_id, None)

        task.add_done_callback(_on_done)
        return {"triggered": True, "status": "running", "session_id": session_id}

    def get_analysis_status(self, session_id: str) -> dict:
        """Query async analysis task status."""
        if session_id in self._task_results:
            result = self._task_results.pop(session_id)
            return {"status": "completed", **result.to_dict()}
        if session_id in self._running_tasks:
            return {
                "status": "running",
                "phase": self._task_phases.get(session_id, "unknown"),
                "session_id": session_id,
            }
        return {"status": "not_found", "session_id": session_id}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _notify_analysis_result(self, session_id: str, report: VerticalTaintReport) -> None:
        """Log analysis result. Report is persisted in DB and accessible via ApiPort."""
        malicious_nodes = [
            v.node_did for v in report.node_verdicts
            if v.severity in ("medium", "high")
        ]
        logger.warning(
            "Security Alert: session={}, verdict={}, malicious_nodes={}",
            session_id, report.overall_verdict, malicious_nodes,
        )
