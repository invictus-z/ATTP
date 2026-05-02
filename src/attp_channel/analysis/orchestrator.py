"""Analysis orchestrator — coordinates semantic taint analysis lifecycle."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from attp_channel.logging import get_logger
from attp_channel.analysis.models import IntentDescriptor, TaintReport

if TYPE_CHECKING:
    from attp_channel.analysis.analyzer import SemanticTaintAnalyzer
    from attp_channel.protocol.tracer import MessageTracer
    from attp_channel.sessions import SessionManager
    from attp_channel.web_app import WebApp

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
    """Coordinates intent extraction, report counting, and analysis scheduling."""

    def __init__(
        self,
        analyzer: SemanticTaintAnalyzer,
        session_manager: SessionManager,
        tracer: MessageTracer,
        web_app: WebApp,
        batch_size: int = 10,
    ):
        self._analyzer = analyzer
        self._session_manager = session_manager
        self._tracer = tracer
        self._web_app = web_app
        self._batch_size = batch_size
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, session_id: str) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    # ------------------------------------------------------------------
    # Callbacks (wired into server / web_app)
    # ------------------------------------------------------------------

    async def on_field_c_recorded(self, session_id: str, content: str) -> None:
        """Called when a User->Agent message (field c) is recorded.

        Extracts intent on the first user message of a session.
        """
        session = self._session_manager.get_or_create(session_id)
        if session.get_intent():
            return

        intent = await self._analyzer.extract_intent(content)
        if intent:
            session.set_intent(intent.to_dict())
            self._session_manager.save(session)
            logger.info("Intent extracted for session={}", session_id)

    async def on_record_received(self, session_id: str) -> None:
        """Called by server when a record message is received.

        Increments report counter and triggers analysis if batch size reached.
        """
        async with self._get_lock(session_id):
            session = self._session_manager.get_or_create(session_id)
            count = session.increment_report_count()
            self._session_manager.save(session)

            if count >= self._batch_size:
                logger.info(
                    "Report batch size reached ({}/{}), triggering analysis for session={}",
                    count, self._batch_size, session_id,
                )
                await self.run_analysis(session_id, is_final=False)

    async def on_session_end(self, session_id: str) -> None:
        """Called when a session ends.

        Runs final analysis on any remaining unchecked traces.
        """
        async with self._get_lock(session_id):
            session = self._session_manager.get(session_id)
            if not session:
                return
            state = session.get_analysis_state()
            if state["report_count"] > 0:
                logger.info("Session {} ending, running final analysis", session_id)
                await self.run_analysis(session_id, is_final=True)
        self._locks.pop(session_id, None)

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
            logger.warning(
                "Cannot run analysis for session={}: no intent extracted",
                session_id,
            )
            return AnalysisResult(triggered=False, reason="no_intent")

        intent = IntentDescriptor.from_dict(intent_data)

        # Recover unchecked traces
        last_id = state["last_trace_id"]
        traces, max_id = await self._tracer.recover_traces_since(session_id, last_id)

        if not traces:
            session.reset_report_count()
            self._session_manager.save(session)
            return AnalysisResult(triggered=False, reason="no_unanalyzed_traces")

        batch_index = state["batch_index"] + 1
        previous_context = state["context"]

        logger.info(
            "Running analysis: session={}, batch={}, traces={}, is_final={}",
            session_id, batch_index, len(traces), is_final,
        )

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

        # Notify user if suspicious or malicious
        if report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(session_id, report)

        logger.info(
            "Analysis complete: session={}, verdict={}, nodes_checked={}",
            session_id, report.overall_verdict, len(report.node_verdicts),
        )
        return AnalysisResult(triggered=True, report=report)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _notify_analysis_result(self, session_id: str, report) -> None:
        """Push analysis result to the WebUI as a system notification."""
        verdict = report.overall_verdict
        summary = report.summary
        malicious_nodes = [
            v.node_did for v in report.node_verdicts
            if v.severity in ("medium", "high")
        ]
        notification = (
            f"[Security Alert] Semantic Taint Analysis detected: {verdict}\n"
            f"Summary: {summary}\n"
        )
        if malicious_nodes:
            notification += f"Suspicious nodes: {', '.join(malicious_nodes)}"

        await self._web_app.record_message(notification, {
            "Session_ID": session_id,
            "is_analysis_alert": True,
            "verdict": verdict,
            "summary": summary,
        })
