"""Horizontal Axis — 横向分析编排器。

镜像纵向编排器的设计模式：
- per-did asyncio.Lock
- per-did 游标状态持久化
- 异步任务管理
- 累积计数触发机制
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from attp.app.logging import get_logger
from attp.core.analysis.horizontal.analyzer import _derive_node_type
from attp.core.analysis.horizontal.models import HorizontalTaintReport

if TYPE_CHECKING:
    from attp.core.analysis.horizontal.analyzer import HorizontalTaintAnalyzer
    from attp.core.sessions.protocol_node.management.horizontal_state import HorizontalAnalysisManager
    from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("HorizontalAnalysis")


@dataclass
class HorizontalAnalysisResult:
    """Result of a horizontal analysis run."""

    triggered: bool
    reason: str = ""
    report: HorizontalTaintReport | None = None

    def to_dict(self) -> dict:
        d: dict = {"triggered": self.triggered, "reason": self.reason}
        if self.report:
            d["report"] = self.report.to_dict()
        return d


class HorizontalOrchestrator:
    """Coordinates cross-session DID behavior analysis.

    Trigger mechanisms:
        1. Automatic: VerticalOrchestrator calls ``on_vertical_analysis_completed(did, session_id)``
           after each vertical analysis. Accumulates count; triggers when threshold reached.
        2. Manual: API calls ``trigger_analysis_async(did)`` directly.
    """

    def __init__(
        self,
        analyzer: HorizontalTaintAnalyzer,
        horizontal_state_mgr: HorizontalAnalysisManager,
        tracer: ProtocolTracer,
        accumulation_threshold: int = 5,
    ):
        self._analyzer = analyzer
        self._state_mgr = horizontal_state_mgr
        self._tracer = tracer
        self._threshold = accumulation_threshold
        self._locks: dict[str, asyncio.Lock] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_results: dict[str, HorizontalAnalysisResult] = {}
        self._task_phases: dict[str, str] = {}

    def _get_lock(self, did: str) -> asyncio.Lock:
        if did not in self._locks:
            self._locks[did] = asyncio.Lock()
        return self._locks[did]

    # ------------------------------------------------------------------
    # Accumulation trigger (called by VerticalOrchestrator)
    # ------------------------------------------------------------------

    async def on_vertical_analysis_completed(self, did: str, session_id: str) -> dict:
        """Called after each vertical analysis completes.

        Increments accumulation counter for the DID.
        Triggers horizontal analysis if threshold reached.

        Returns:
            {"accumulated": int, "threshold": int, "triggered": bool}
        """
        count = await self._state_mgr.increment_accumulation(did)
        triggered = False

        if count >= self._threshold:
            logger.info(
                "Horizontal accumulation threshold reached ({}/{}), triggering for did={}",
                count, self._threshold, did,
            )
            # Fire async — do not block the vertical pipeline
            await self.trigger_analysis_async(did)
            triggered = True

        return {
            "accumulated": count,
            "threshold": self._threshold,
            "triggered": triggered,
        }

    # ------------------------------------------------------------------
    # Core analysis runner
    # ------------------------------------------------------------------

    async def run_analysis(self, did: str) -> HorizontalAnalysisResult:
        """Run horizontal analysis for a DID.

        Flow:
        1. Restore per-did cursor state
        2. Query traces across all sessions (incremental cursor)
        3. Derive node_type from field_type
        4. Build CrossSessionProfile
        5. Select node_type-specific Prompt
        6. Call LLM
        7. Persist report
        8. Update cursor, reset accumulation
        9. If malicious → update node_dossiers
        """
        await self._state_mgr.restore_state(did)
        cursor = await self._state_mgr.get_cursor(did)

        last_trace_id = cursor.get("last_trace_id", 0)
        batch_index = cursor.get("batch_index", 0)
        previous_context = cursor.get("context", "")

        # Step 2: Recover traces
        self._task_phases[did] = "recovering_traces"
        traces, max_id = await self._tracer.storage.recover_traces_by_did_since(
            did, last_trace_id,
        )

        if not traces:
            return HorizontalAnalysisResult(triggered=False, reason="no_new_traces")

        # Step 3: Derive node_type
        node_type = _derive_node_type(traces, did)

        batch_index += 1

        logger.info(
            "Running horizontal analysis: did={}, node_type={}, batch={}, traces={}",
            did, node_type, batch_index, len(traces),
        )

        # Step 4-6: Analyze
        self._task_phases[did] = "analyzing"
        report = await self._analyzer.analyze(
            did=did,
            node_type=node_type,
            batch_index=batch_index,
            from_trace_id=last_trace_id,
            to_trace_id=max_id,
            traces=traces,
            previous_context=previous_context,
        )

        # Step 7: Persist report
        self._task_phases[did] = "saving_results"
        report_json = json.dumps(report.to_dict(), ensure_ascii=False)
        await self._tracer.storage.save_horizontal_report(report_json)

        # Step 8: Update cursor and reset accumulation
        await self._state_mgr.update_cursor(
            did,
            batch_index=batch_index,
            last_trace_id=max_id,
            context=report.context_summary,
            node_type=node_type,
        )
        await self._state_mgr.reset_accumulation(did)

        # Step 9: Update dossier if malicious
        if report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(did, report)

        logger.info(
            "Horizontal analysis complete: did={}, verdict={}, sessions_scanned={}",
            did, report.overall_verdict, report.sessions_scanned,
        )
        return HorizontalAnalysisResult(triggered=True, report=report)

    # ------------------------------------------------------------------
    # Async task management
    # ------------------------------------------------------------------

    async def trigger_analysis_async(self, did: str) -> dict:
        """Fire-and-forget horizontal analysis task."""
        if did in self._running_tasks:
            return {"triggered": True, "status": "already_running", "did": did}

        async def _task_body():
            try:
                async with self._get_lock(did):
                    result = await self.run_analysis(did)
                return result
            except Exception as e:
                logger.error("Async horizontal analysis failed for did={}: {}", did, e)
                return HorizontalAnalysisResult(triggered=False, reason=f"task_error: {e}")

        task = asyncio.create_task(_task_body())
        self._running_tasks[did] = task
        self._task_phases[did] = "starting"

        def _on_done(t: asyncio.Task):
            self._task_results[did] = t.result()
            self._running_tasks.pop(did, None)
            self._task_phases.pop(did, None)

        task.add_done_callback(_on_done)
        return {"triggered": True, "status": "running", "did": did}

    def get_analysis_status(self, did: str) -> dict:
        """Query async horizontal analysis task status."""
        if did in self._task_results:
            result = self._task_results.pop(did)
            return {"status": "completed", **result.to_dict()}
        if did in self._running_tasks:
            return {
                "status": "running",
                "phase": self._task_phases.get(did, "unknown"),
                "did": did,
            }
        return {"status": "not_found", "did": did}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _notify_analysis_result(self, did: str, report: HorizontalTaintReport) -> None:
        """Log and record horizontal analysis result."""
        verdict = report.did_verdict
        logger.warning(
            "Horizontal Security Alert: did={}, verdict={}, severity={}, score={}",
            did, report.overall_verdict, verdict.severity, verdict.taint_score,
        )
        # Update node_dossiers via existing malicious infrastructure
        if verdict.severity in ("medium", "high"):
            await self._tracer.storage.upsert_dossier(
                malicious_did=did,
                evidence_type="horizontal_taint_detected",
                session_id=report.sessions_scanned > 0 and "cross_session" or "",
                description=f"横向分析检测到跨Session恶意行为: {report.summary}",
            )
