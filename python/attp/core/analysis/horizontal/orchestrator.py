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
from attp.core.analysis.horizontal.models import HorizontalIntentReport
from attp.core.sse import EventType, Topic

if TYPE_CHECKING:
    from attp.core.analysis.horizontal.analyzer import HorizontalIntentAnalyzer
    from attp.core.sessions.protocol_node.management.horizontal_state import HorizontalAnalysisManager
    from attp.core.sse import EventBroker
    from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("HorizontalAnalysis")


@dataclass
class HorizontalAnalysisResult:
    """Result of a horizontal analysis run."""

    triggered: bool
    reason: str = ""
    report: HorizontalIntentReport | None = None

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
        analyzer: HorizontalIntentAnalyzer,
        horizontal_state_mgr: HorizontalAnalysisManager,
        tracer: ProtocolTracer,
        accumulation_threshold: int = 5,
        event_broker: EventBroker | None = None,
    ):
        self._analyzer = analyzer
        self._state_mgr = horizontal_state_mgr
        self._tracer = tracer
        self._threshold = accumulation_threshold
        self._broker = event_broker
        self._locks: dict[str, asyncio.Lock] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_results: dict[str, HorizontalAnalysisResult] = {}
        self._task_phases: dict[str, str] = {}

    async def _set_phase(self, did: str, phase: str) -> None:
        """更新任务阶段并发布 ``analysis.progress`` 事件。"""
        self._task_phases[did] = phase
        if self._broker:
            await self._broker.publish(
                EventType.ANALYSIS_PROGRESS,
                {"axis": "horizontal", "did": did, "phase": phase},
                topic=Topic.ANALYSIS,
            )

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

        发布 ``horizontal.accumulated`` 事件（topic=analysis, payload 含 did），
        使前端订阅该 DID 的客户端能实时刷新横向累计状态（pending_count 等）。

        Returns:
            {"pending_count": int, "threshold": int, "triggered": bool}
        """
        count = await self._state_mgr.increment_pending_count(did)
        triggered = False

        if self._broker:
            await self._broker.publish(
                EventType.HORIZONTAL_ACCUMULATED,
                {
                    "axis": "horizontal",
                    "did": did,
                    "session_id": session_id,
                    "pending_count": count,
                    "threshold": self._threshold,
                },
                topic=Topic.ANALYSIS,
            )

        if count >= self._threshold:
            logger.info(
                "Horizontal accumulation threshold reached ({}/{}), triggering for did={}",
                count, self._threshold, did,
            )
            # Fire async — do not block the vertical pipeline
            await self.trigger_analysis_async(did)
            triggered = True

        return {
            "pending_count": count,
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
        await self._set_phase(did, "recovering_traces")
        traces, max_id = await self._tracer.storage.recover_traces_by_did_since(
            did, last_trace_id,
        )

        if not traces:
            if self._broker:
                await self._broker.publish(
                    EventType.ANALYSIS_REPORT,
                    {"axis": "horizontal", "did": did,
                     "triggered": False, "reason": "no_new_traces"},
                    topic=Topic.ANALYSIS,
                )
            return HorizontalAnalysisResult(triggered=False, reason="no_new_traces")

        # Step 3: Derive node_type
        node_type = _derive_node_type(traces, did)

        batch_index += 1

        logger.info(
            "Running horizontal analysis: did={}, node_type={}, batch={}, traces={}",
            did, node_type, batch_index, len(traces),
        )

        # Step 4-6: Analyze
        await self._set_phase(did, "analyzing")
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
        await self._set_phase(did, "saving_results")
        report_json = json.dumps(report.to_dict(), ensure_ascii=False)
        report_row_id = await self._tracer.storage.save_horizontal_report(report_json)

        # Step 8: Update cursor and reset accumulation FIRST, then publish —
        # 否则前端收到 analysis.report 立即拉取状态时会读到旧的 batch_index /
        # last_trace_id / pending_count。
        await self._state_mgr.update_cursor(
            did,
            batch_index=batch_index,
            last_trace_id=max_id,
            context=report.context_summary,
            node_type=node_type,
        )
        await self._state_mgr.reset_pending_count(did)

        if self._broker:
            await self._broker.publish(
                EventType.ANALYSIS_REPORT,
                {
                    "axis": "horizontal",
                    "did": did,
                    "batch_index": batch_index,
                    "verdict": report.overall_verdict,
                    "summary": report.summary,
                    "report_id": report_row_id,
                },
                topic=Topic.ANALYSIS,
            )

        # Step 9: Update malicious_reports + dossier if malicious
        if report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(did, report, report_row_id)

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
        await self._set_phase(did, "starting")

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

    async def _notify_analysis_result(
        self, did: str, report: HorizontalIntentReport, report_row_id: int,
    ) -> None:
        """记录横向分析发现的恶意节点：写入 malicious_reports + 更新 dossier。"""
        verdict = report.did_verdict
        logger.warning(
            "Horizontal Security Alert: did={}, verdict={}, severity={}, score={}",
            did, report.overall_verdict, verdict.severity, verdict.taint_score,
        )
        if verdict.severity in ("medium", "high"):
            await self._tracer.storage.save_malicious_report({
                "source": "horizontal_analysis",
                "target_did": did,
                "node_type": verdict.node_type,
                "session_id": "",
                "evidence_type": verdict.threat_pattern,
                "severity": verdict.severity,
                "taint_score": verdict.taint_score,
                "evidence_description": verdict.evidence,
                "nonce": "",
                "report_id": report_row_id,
                "raw_evidence": {"evidence_items": [e.to_dict() for e in verdict.evidence_items]},
                "timestamp": report.timestamp,
            })
