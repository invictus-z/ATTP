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
from attp.core.analysis.vertical.analyzer import _derive_node_type
from attp.core.analysis.vertical.models import NodeIntentVerdict, VerticalIntentReport

if TYPE_CHECKING:
    from attp.core.analysis.vertical.analyzer import VerticalIntentAnalyzer
    from attp.core.sessions.protocol_node.management.vertical_state import VerticalAnalysisManager
    from attp.core.events import EventBroker
    from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("VerticalAnalysis")


@dataclass
class VerticalAnalysisResult:
    """Result of a vertical analysis run."""

    triggered: bool
    reason: str = ""
    report: VerticalIntentReport | None = None

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
        analyzer: VerticalIntentAnalyzer,
        vertical_state_mgr: VerticalAnalysisManager,
        tracer: ProtocolTracer,
        batch_size: int = 10,
        horizontal_trigger_callback: Callable[[str, str], Awaitable[None]] | None = None,
        event_broker: EventBroker | None = None,
    ):
        self._analyzer = analyzer
        self._state_mgr = vertical_state_mgr
        self._tracer = tracer
        self._batch_size = batch_size
        self._horizontal_trigger_callback = horizontal_trigger_callback
        self._broker = event_broker
        self._locks: dict[str, asyncio.Lock] = {}
        self._restored_sessions: set[str] = set()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_results: dict[str, VerticalAnalysisResult] = {}
        self._task_phases: dict[str, str] = {}

    async def _set_phase(self, session_id: str, phase: str) -> None:
        """更新任务阶段并发布 ``analysis.progress`` 事件。"""
        self._task_phases[session_id] = phase
        if self._broker:
            await self._broker.publish(
                "analysis.progress",
                {"axis": "vertical", "session_id": session_id, "phase": phase},
                topic="analysis",
            )

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
            # 兜底：LLM 意图提取失败时，用 U2A 原文构造最小意图，
            # 避免后续 run_analysis 因 no_intent 静默放弃整段会话分析（导致漏检）。
            from attp.core.analysis.base_models import IntentDescriptor
            fallback = IntentDescriptor(
                original_task=content,
                core_objective=content[:200],
                constraints=[],
                involved_capabilities=[],
                risk_level="medium",
            )
            await self._state_mgr.set_intent(session_id, fallback.to_dict())
            logger.warning(
                "Intent extraction failed for session={}, applied fallback intent from raw U2A",
                session_id,
            )

    async def on_record_received(self, session_id: str) -> None:
        """Called by DataPort when a record message is received.

        Increments report counter and triggers analysis if batch size reached.
        """
        async with self._get_lock(session_id):
            count = await self._state_mgr.increment_pending_count(session_id)

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
        """Run vertical semantic intent tracking for a session.

        IMPORTANT: Caller must hold the per-session lock.
        """
        state = await self._state_mgr.get_state(session_id)
        intent_data = state.get("intent")

        if not intent_data:
            logger.warning(
                "Cannot run vertical analysis for session={}: no intent extracted",
                session_id,
            )
            if self._broker:
                await self._broker.publish(
                    "analysis.report",
                    {"axis": "vertical", "session_id": session_id,
                     "triggered": False, "reason": "no_intent"},
                    topic="analysis",
                )
            return VerticalAnalysisResult(triggered=False, reason="no_intent")

        intent = IntentDescriptor.from_dict(intent_data)

        # Recover unchecked traces
        await self._set_phase(session_id, "recovering_traces")
        last_id = state["last_trace_id"]
        traces, max_id = await self._tracer.recover_traces_since(session_id, last_id)

        if not traces:
            await self._state_mgr.reset_pending_count(session_id)
            if self._broker:
                await self._broker.publish(
                    "analysis.report",
                    {"axis": "vertical", "session_id": session_id,
                     "triggered": False, "reason": "no_unanalyzed_traces"},
                    topic="analysis",
                )
            return VerticalAnalysisResult(triggered=False, reason="no_unanalyzed_traces")

        batch_index = state["batch_index"] + 1
        previous_context = state["context"]

        logger.info(
            "Running vertical analysis: session={}, batch={}, traces={}, is_final={}",
            session_id, batch_index, len(traces), is_final,
        )

        await self._set_phase(session_id, "analyzing")
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
        await self._set_phase(session_id, "saving_results")
        report_json = json.dumps(report.to_dict(), ensure_ascii=False)
        report_row_id = await self._tracer.save_analysis_report(report_json)

        # Update session state FIRST, then publish — 否则前端收到 analysis.report
        # 立即拉取状态时会读到旧的 batch_index / last_trace_id / pending_count。
        await self._state_mgr.reset_pending_count(session_id)
        await self._state_mgr.update_cursor(
            session_id, batch_index=batch_index,
            last_trace_id=max_id, context=report.context_summary,
        )

        if self._broker:
            await self._broker.publish(
                "analysis.report",
                {
                    "axis": "vertical",
                    "session_id": session_id,
                    "batch_index": batch_index,
                    "verdict": report.overall_verdict,
                    "summary": report.summary,
                    "report_id": report_row_id,
                },
                topic="analysis",
            )

        # Notify if suspicious or malicious
        if report.overall_verdict == "error":
            logger.error("Vertical analysis error for session={}: {}", session_id, report.summary)
        elif report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(session_id, report, report_row_id, traces)

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
        await self._set_phase(session_id, "starting")

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

    @staticmethod
    def _merge_verdicts_by_did(
        verdicts: list[NodeIntentVerdict],
    ) -> list[tuple[NodeIntentVerdict, list[list[int]]]]:
        """将同一 DID 的多条 verdict 合并为一条，按 DID 去重但不丢失证据。

        合并策略：
        - severity / taint_score：取最严重那条（high > medium）
        - deviation_type / influence_type：取最高分 verdict 的值（代表最核心偏离类型）
        - evidence（描述）：全部合并，每条标注其 hop，体现多个通信上下文
        - evidence_items：全部合并去重（按 description），保留所有 trace_ids
          —— trace_ids 即为具体犯错地点，一条不漏
        - hop_count：记录所有涉及 hop，随返回值一并输出（存入 raw_evidence.hops_involved）

        Returns:
            [(merged_verdict, hops_involved), ...]，每个 DID 一项
        """
        severity_rank = {"none": 0, "low": 1, "medium": 2, "high": 3}

        grouped: dict[str, list[NodeIntentVerdict]] = {}
        for v in verdicts:
            grouped.setdefault(v.node_did, []).append(v)

        merged: list[tuple[NodeIntentVerdict, list[list[int]]]] = []
        for did, did_verdicts in grouped.items():
            # 最高分（最严重）的 verdict 作为基础，决定 severity / deviation_type 等
            primary = max(
                did_verdicts,
                key=lambda v: (severity_rank.get(v.severity, 0), v.taint_score),
            )

            # 收集该 DID 涉及的所有 hop（去重）
            all_hops: list[list[int]] = []
            for v in did_verdicts:
                hc = list(v.hop_count)
                if hc not in all_hops:
                    all_hops.append(hc)

            # 合并 evidence 描述，每条标注来源 hop，体现多个通信上下文
            evidence_parts: list[str] = []
            seen_evidence: set[str] = set()
            for v in did_verdicts:
                if v.evidence and v.evidence not in seen_evidence:
                    evidence_parts.append(f"hop={list(v.hop_count)}: {v.evidence}")
                    seen_evidence.add(v.evidence)
            merged_evidence = " | ".join(evidence_parts) if evidence_parts else primary.evidence

            # 合并 evidence_items（按 description 去重），保留所有 trace_ids（具体犯错地点）
            merged_items = []
            seen_desc: set[str] = set()
            for v in did_verdicts:
                for ei in v.evidence_items:
                    if ei.description not in seen_desc:
                        merged_items.append(ei)
                        seen_desc.add(ei.description)

            merged_v = NodeIntentVerdict(
                node_did=did,
                hop_count=list(primary.hop_count),
                aligned=primary.aligned,
                deviation_type=primary.deviation_type,
                influence_detected=primary.influence_detected,
                influence_type=primary.influence_type,
                evidence=merged_evidence,
                evidence_items=merged_items,
                severity=primary.severity,
                taint_score=primary.taint_score,
            )
            merged.append((merged_v, all_hops))

        return merged

    async def _notify_analysis_result(
        self,
        session_id: str,
        report: VerticalIntentReport,
        report_row_id: int,
        traces: list[dict],
    ) -> None:
        """记录纵向分析发现的恶意节点：写入 malicious_reports + 更新 dossier。

        按 DID 去重：同一 batch 内一个 DID 只产生一条 malicious_report，
        但合并该 DID 所有 hop 的 evidence_items（含全部 trace_ids），确保具体犯错地点不丢失。
        """
        malicious_verdicts = [
            v for v in report.node_verdicts
            if v.severity in ("medium", "high")
        ]
        # 按 DID 合并：同一节点的多条 hop-verdict 合为一条
        merged = self._merge_verdicts_by_did(malicious_verdicts)

        for merged_v, hops_involved in merged:
            node_type = _derive_node_type(traces, merged_v.node_did)

            await self._tracer.storage.save_malicious_report({
                "source": "vertical_analysis",
                "target_did": merged_v.node_did,
                "node_type": node_type,
                "session_id": session_id,
                "evidence_type": merged_v.deviation_type,
                "severity": merged_v.severity,
                "taint_score": merged_v.taint_score,
                "evidence_description": merged_v.evidence,
                "nonce": "",
                "report_id": report_row_id,
                "raw_evidence": {
                    "evidence_items": [e.to_dict() for e in merged_v.evidence_items],
                    "hops_involved": hops_involved,
                    "verdict_count_merged": len(
                        [v for v in malicious_verdicts if v.node_did == merged_v.node_did]
                    ),
                },
                "timestamp": report.timestamp,
            })

        logger.warning(
            "Vertical Security Alert: session={}, verdict={}, malicious_nodes={}",
            session_id, report.overall_verdict,
            [v.node_did for v, _ in merged],
        )
