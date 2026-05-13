"""Analysis orchestrator — coordinates semantic taint analysis lifecycle."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from attp.app.logging import get_logger
from attp.core.analysis.models import IntentDescriptor, TaintReport

if TYPE_CHECKING:
    from attp.core.analysis.analyzer import SemanticTaintAnalyzer
    from attp.core.tracer import MessageTracer
    from attp.core.sessions.protocol_node import ProtocolSessionManager

logger = get_logger("Analysis")


@dataclass
class AnalysisResult:
    """Result of a manual analysis trigger."""

    triggered: bool
    reason: str = ""
    report: TaintReport | None = None

    def to_dict(self) -> dict:
        d: dict = {"triggered": self.triggered, "reason": self.reason}
        if self.report:
            d["report"] = self.report.to_dict()
        return d


class AnalysisOrchestrator:
    """Coordinates intent extraction, report counting, and analysis scheduling.

    Entirely driven by DataPort record reception — no dependency on web layer.
    Analysis state is persisted to SQLite via MessageTracer for crash recovery.
    """

    def __init__(
        self,
        analyzer: SemanticTaintAnalyzer,
        session_manager: ProtocolSessionManager,
        tracer: MessageTracer,
        batch_size: int = 10,
    ):
        self._analyzer = analyzer
        self._session_manager = session_manager
        self._tracer = tracer
        self._batch_size = batch_size
        self._locks: dict[str, asyncio.Lock] = {}
        self._restored_sessions: set[str] = set()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_results: dict[str, AnalysisResult] = {}
        self._task_phases: dict[str, str] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    async def _persist_state(self, session_id: str) -> None:
        """Write current analysis state to SQLite."""
        session = self._session_manager.get(session_id)
        if not session:
            return
        state = session.get_analysis_state()
        await self._tracer.save_analysis_session(session_id, {
            "intent_json": json.dumps(state["intent"], ensure_ascii=False) if state["intent"] else None,
            "report_count": state["report_count"],
            "last_trace_id": state["last_trace_id"],
            "batch_index": state["batch_index"],
            "context": state["context"],
        })

    async def _restore_state(self, session_id: str) -> None:
        """Restore analysis state from SQLite into Session (only if Session has no state)."""
        if session_id in self._restored_sessions:
            return
        session = self._session_manager.get_or_create(session_id)
        if session.get_analysis_state()["last_trace_id"] != 0:
            return
        saved = await self._tracer.load_analysis_session(session_id)
        if not saved:
            return
        if saved["intent_json"]:
            session.set_intent(json.loads(saved["intent_json"]))
        session.update_analysis_cursor(
            batch_index=saved["batch_index"],
            last_trace_id=saved["last_trace_id"],
            context=saved["context"] or "",
        )
        for _ in range(saved["report_count"]):
            session.increment_report_count()
        self._session_manager.save(session)
        self._restored_sessions.add(session_id)
        logger.info("Restored analysis state for session={} from SQLite", session_id)

    # ------------------------------------------------------------------
    # Callbacks (wired into DataPort)
    # ------------------------------------------------------------------

    async def on_field_U2A_recorded(self, session_id: str, content: str) -> None:
        """Called when a User->Agent message (field c / U2A) is recorded.

        Extracts intent from the first user message of a session.
        Caches content for retry on subsequent triggers if extraction fails.
        """
        await self._restore_state(session_id)
        session = self._session_manager.get_or_create(session_id)

        session.set_metadata("_pending_intent_content", content)

        if session.get_intent():
            return

        intent = await self._analyzer.extract_intent(content)
        if intent:
            session.set_intent(intent.to_dict())
            session.set_metadata("_intent_retry_count", None)
            self._session_manager.save(session)
            await self._persist_state(session_id)
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
            await self._restore_state(session_id)
            session = self._session_manager.get_or_create(session_id)
            count = session.increment_report_count()
            self._session_manager.save(session)
            await self._persist_state(session_id)

            if count >= self._batch_size:
                logger.info(
                    "Report batch size reached ({}/{}), triggering analysis for session={}",
                    count, self._batch_size, session_id,
                )
                await self.run_analysis(session_id, is_final=False)

    # ------------------------------------------------------------------
    # Core analysis runner
    # ------------------------------------------------------------------

    async def run_analysis(self, session_id: str, is_final: bool = False) -> AnalysisResult:
        """Run semantic taint analysis for a session.

        IMPORTANT: Caller must hold the per-session lock.

        Recovers unchecked traces, calls LLM, and updates state.
        """
        session = self._session_manager.get_or_create(session_id)
        state = session.get_analysis_state()
        intent_data = state.get("intent")

        if not intent_data:
            retry_count = session.get_metadata("_intent_retry_count", 0)
            pending_content = session.get_metadata("_pending_intent_content")
            if pending_content and retry_count < 3:
                session.set_metadata("_intent_retry_count", retry_count + 1)
                self._session_manager.save(session)
                logger.info(
                    "Retrying intent extraction ({}/3) for session={}",
                    retry_count + 1, session_id,
                )
                intent = await self._analyzer.extract_intent(pending_content)
                if intent:
                    session.set_intent(intent.to_dict())
                    session.set_metadata("_intent_retry_count", None)
                    self._session_manager.save(session)
                    await self._persist_state(session_id)
                    intent_data = session.get_intent()
                else:
                    return AnalysisResult(triggered=False, reason="no_intent_retry_exhausted")
            else:
                logger.warning(
                    "Cannot run analysis for session={}: no intent extracted",
                    session_id,
                )
                return AnalysisResult(triggered=False, reason="no_intent")

        intent = IntentDescriptor.from_dict(intent_data)

        # Recover unchecked traces
        self._task_phases[session_id] = "recovering_traces"
        last_id = state["last_trace_id"]
        traces, max_id = await self._tracer.recover_traces_since(session_id, last_id)

        if not traces:
            session.reset_report_count()
            self._session_manager.save(session)
            await self._persist_state(session_id)
            return AnalysisResult(triggered=False, reason="no_unanalyzed_traces")

        batch_index = state["batch_index"] + 1
        previous_context = state["context"]

        logger.info(
            "Running analysis: session={}, batch={}, traces={}, is_final={}",
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

        # Update session state: mark traces as checked, store context
        session.reset_report_count()
        session.update_analysis_cursor(
            batch_index=batch_index,
            last_trace_id=max_id,
            context=report.context_summary,
        )
        self._session_manager.save(session)
        await self._persist_state(session_id)

        # Notify user if suspicious or malicious
        if report.overall_verdict == "error":
            logger.error("Analysis error for session={}: {}", session_id, report.summary)
        elif report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(session_id, report)

        logger.info(
            "Analysis complete: session={}, verdict={}, nodes_checked={}",
            session_id, report.overall_verdict, len(report.node_verdicts),
        )
        return AnalysisResult(triggered=True, report=report)

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
                logger.error("Async analysis task failed for session={}: {}", session_id, e)
                return AnalysisResult(triggered=False, reason=f"task_error: {e}")

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

    async def _notify_analysis_result(self, session_id: str, report) -> None:
        """Log analysis result. Report is persisted in DB and accessible via ApiPort."""
        malicious_nodes = [
            v.node_did for v in report.node_verdicts
            if v.severity in ("medium", "high")
        ]
        logger.warning(
            "Security Alert: session={}, verdict={}, malicious_nodes={}",
            session_id, report.overall_verdict, malicious_nodes,
        )
