"""Horizontal Axis — 横向编排器（逐跳改版：per-DID F 累加 + 跨会话确认）。

- ``on_hop_scored``：纵轴每打一跳分即调用，per-DID 累加 F（跨会话叠加，纯平方和 Σ s²）；
  达 ``F > R_S`` 触发横轴确认（无折扣、无死区、无体积封顶）。
- ``run_analysis``：候选会话 ≤ α 直接取全量，否则按 ``W(σ)=Σ s²`` 取 α 个（高危兜底）→
  H-Reasoner 确认（汇入上一次确认报告，防会话集拆分规避）→ 确认则告警，良性则记摘要闭案
  （重置 F、推进游标）。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from attp.app.logging import get_logger
from attp.core.analysis.base_models import SEVERITY_RANK
from attp.core.analysis.horizontal.analyzer import (
    FIELD_TYPE_TO_SENDER_NODE_TYPE,
    _derive_node_type_from_scores,
)
from attp.core.analysis.horizontal.models import ConfirmationReport, ConfirmationVerdict
from attp.core.sse import EventType, Topic

if TYPE_CHECKING:
    from attp.core.analysis.horizontal.analyzer import HorizontalIntentAnalyzer
    from attp.core.sessions.protocol_node.management.horizontal_state import HorizontalAnalysisManager
    from attp.core.sse import EventBroker
    from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("HorizontalAnalysis")


@dataclass
class HorizontalAnalysisResult:
    """Result of a horizontal confirmation run."""

    triggered: bool
    reason: str = ""
    report: ConfirmationReport | None = None

    def to_dict(self) -> dict:
        d: dict = {"triggered": self.triggered, "reason": self.reason}
        if self.report:
            d["report"] = self.report.to_dict()
        return d


class HorizontalOrchestrator:
    """跨会话确认编排：per-DID F 累加 + α 会话确认。"""

    def __init__(
        self,
        analyzer: HorizontalIntentAnalyzer,
        horizontal_state_mgr: HorizontalAnalysisManager,
        tracer: ProtocolTracer,
        r_s: float = 25.0,
        alpha: int = 10,
        rho: float = 8.0,
        concurrency: int = 8,
        event_broker: EventBroker | None = None,
    ):
        self._analyzer = analyzer
        self._state_mgr = horizontal_state_mgr
        self._tracer = tracer
        self._r_s = r_s
        self._alpha = alpha
        self._rho = rho
        self._broker = event_broker
        self._sem = asyncio.Semaphore(concurrency)

        self._locks: dict[str, asyncio.Lock] = {}
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_results: dict[str, HorizontalAnalysisResult] = {}
        self._task_phases: dict[str, str] = {}

    async def _set_phase(self, did: str, phase: str) -> None:
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
    # F 累加（纵轴每打一跳分调用）
    # ------------------------------------------------------------------

    async def on_hop_scored(
        self, did: str, session_id: str, trace_id: int, score: float, field_type: str,
    ) -> dict:
        """单跳分数到达 → per-DID 累加 F/体积，达阈值触发确认（异步）。"""
        async with self._get_lock(did):
            # 纯平方和：f_delta = s²（无死区 d、无折扣 γ）；F 单调递增，分散小偏移终将触发
            f_delta = score ** 2
            node_type = FIELD_TYPE_TO_SENDER_NODE_TYPE.get(field_type, "agent")
            f_value, volume = await self._state_mgr.accumulate(
                did, f_delta, node_type,
            )

        if self._broker:
            await self._broker.publish(
                EventType.HORIZONTAL_ACCUMULATED,
                {
                    "axis": "horizontal", "did": did, "session_id": session_id,
                    "trace_id": trace_id, "score": score,
                    "f_value": f_value, "volume": volume,
                    "r_s": self._r_s,
                },
                topic=Topic.ANALYSIS,
            )

        triggered = False
        reason = ""
        if f_value > self._r_s:
            triggered, reason = True, "f_threshold"

        if triggered:
            logger.info(
                "Horizontal trigger: did={}, reason={}, F={:.2f}(R_S={}), volume={}",
                did, reason, f_value, self._r_s, volume,
            )
            if self._broker:
                await self._broker.publish(
                    EventType.HORIZONTAL_TRIGGERED,
                    {"axis": "horizontal", "did": did, "reason": reason,
                     "f_value": f_value, "volume": volume},
                    topic=Topic.ANALYSIS,
                )
            # fire-and-forget，不阻塞纵轴管线
            await self.trigger_analysis_async(did, triggered_by=reason)

        return {"f_value": f_value, "volume": volume, "triggered": triggered, "reason": reason}

    # ------------------------------------------------------------------
    # 确认主流程
    # ------------------------------------------------------------------

    async def run_analysis(self, did: str, triggered_by: str = "manual") -> HorizontalAnalysisResult:
        """对 DID 做跨会话确认。Caller 持 per-DID 锁。"""
        await self._state_mgr.restore_state(did)
        state = await self._state_mgr.get_state(did)
        cursor = state["last_trace_id"]
        node_type = state.get("node_type") or "agent"

        # 1. 取游标以来的逐跳评分
        await self._set_phase(did, "selecting")
        hop_scores = await self._tracer.query_hop_scores_by_did(did, cursor)
        if not hop_scores:
            # 游标已越过全部已打分跳。若有晚到跳（trace_id ≤ cursor）留下滞留 F，清掉——
            # 这些跳不会再被确认（其纵轴 R_T 告警已发），留着 F 只会反复空触发。
            if (state.get("f_value") or 0) > 0 or (state.get("volume") or 0) > 0:
                await self._state_mgr.reset_accumulation(did)
            if self._broker:
                await self._broker.publish(
                    EventType.ANALYSIS_REPORT,
                    {"axis": "horizontal", "did": did,
                     "triggered": False, "reason": "no_new_scores"},
                    topic=Topic.ANALYSIS,
                )
            return HorizontalAnalysisResult(triggered=False, reason="no_new_scores")

        if node_type == "agent":
            node_type = _derive_node_type_from_scores(hop_scores, did) or "agent"

        # 2. 选择 α 个会话（W(σ) 降序 + 高危兜底）
        selected, w_map = self._select_sessions(hop_scores)

        # 3. 取 traces 供确认画像（仅取 content）；游标必须按"已打分跳"推进——
        #    不能用 behavior_traces 的 max（会越过尚未打分的跳，导致它们 no_new_scores
        #    永不确认、F 滞留 >R_S）。
        traces, _ = await self._tracer.storage.recover_traces_by_did_since(did, cursor)
        max_scored = max((h.get("trace_id", 0) for h in hop_scores), default=cursor)
        # 各入选会话"截至本批最后一跳"的累积意图基准——供横轴判"违反授权"
        intents = await self._load_session_intents(selected, max_scored)
        sessions_data = self._build_sessions_data(traces, hop_scores, selected, w_map, intents)

        if not sessions_data:
            # 无可复核会话（兜底/窗口外）→ 闭案推进游标，避免重复触发
            await self._state_mgr.close(did, max_scored, context=state.get("context", ""))
            return HorizontalAnalysisResult(triggered=False, reason="no_selected_sessions")

        # 4. LLM 确认（汇入上一次确认报告，防跨会话集拆分规避）
        await self._set_phase(did, "confirming")
        prior_report = await self._load_prior_report(did)
        async with self._sem:
            verdict = await self._analyzer.confirm(
                did, node_type, sessions_data,
                previous_context=state.get("context", ""),
                prior_report=prior_report,
            )

        overall = self._derive_overall(verdict)
        batch_index = state.get("batch_index", 0) + 1

        report = ConfirmationReport(
            did=did,
            node_type=node_type,
            batch_index=batch_index,
            from_trace_id=cursor,
            to_trace_id=max_scored,
            sessions_scanned=len(sessions_data),
            selected_sessions=sorted(selected),
            verdict=verdict,
            overall_verdict=overall,
            summary=verdict.summary or verdict.evidence[:200],
            context_summary=verdict.context_summary,
            triggered_by=triggered_by,
        )

        # 5. 持久化报告
        await self._set_phase(did, "saving_results")
        report_json = json.dumps(report.to_dict(), ensure_ascii=False)
        report_row_id = await self._tracer.storage.save_horizontal_report(report_json)

        # 6. 告警 / 良性闭案
        if verdict.confirmed:
            await self._notify_confirmed(did, verdict, report_row_id)
        # 闭案：重置 F/体积、推进游标、记录摘要
        await self._state_mgr.close(
            did, max_scored, context=verdict.context_summary or state.get("context", ""),
        )

        if self._broker:
            await self._broker.publish(
                EventType.ANALYSIS_REPORT,
                {
                    "axis": "horizontal", "did": did,
                    "batch_index": batch_index,
                    "confirmed": verdict.confirmed,
                    "verdict": overall,
                    "summary": report.summary,
                    "report_id": report_row_id,
                },
                topic=Topic.ANALYSIS,
            )

        logger.info(
            "Horizontal confirm complete: did={}, confirmed={}, overall={}, sessions={}",
            did, verdict.confirmed, overall, len(sessions_data),
        )
        return HorizontalAnalysisResult(triggered=True, report=report)

    # ------------------------------------------------------------------
    # 会话选择（W(σ) + 高危兜底）
    # ------------------------------------------------------------------

    def _select_sessions(self, hop_scores: list[dict]) -> tuple[set[str], dict[str, float]]:
        """选会话：候选数 ≤ α 直接取全量；否则按 W(σ)=Σ s² 降序取 α 个 + 高危兜底（s≥ρ）。"""
        w_map: dict[str, float] = {}
        high_risk: set[str] = set()
        for h in hop_scores:
            sid = h.get("session_id", "")
            if not sid:
                continue
            s = h.get("score", 0.0)
            w_map[sid] = w_map.get(sid, 0.0) + s ** 2
            if s >= self._rho:
                high_risk.add(sid)

        # α 是超参：候选会话数 ≤ α 时无需排序，直接取全量
        if len(w_map) <= self._alpha:
            return set(w_map.keys()), w_map

        ranked = sorted(w_map.items(), key=lambda kv: kv[1], reverse=True)
        selected: set[str] = {sid for sid, _ in ranked[: self._alpha]}
        # 高危兜底：不占 α 名额
        selected |= high_risk
        return selected, w_map

    async def _load_prior_report(self, did: str) -> str:
        """加载上一次确认报告，渲染成跨 batch 上下文（防会话集拆分规避）。"""
        rows = await self._tracer.storage.recover_horizontal_reports(did)
        if not rows:
            return ""
        # 按 batch_index 升序，最后一行即最近一次确认（本次报告尚未落库）
        prior_dict = json.loads(rows[-1].get("report_json") or "{}")
        return self._format_prior_report(prior_dict)

    @staticmethod
    def _format_prior_report(prior: dict) -> str:
        """把上一次确认报告渲染成 prompt 段落。字段直接取自 report_json（绕开 from_dict 缺陷）。"""
        if not prior:
            return ""
        verdict = prior.get("verdict", {}) or {}
        confirmed = "确认恶意" if (prior.get("confirmed") or verdict.get("confirmed")) else "判为良性"
        sel = prior.get("selected_sessions") or []
        sel_str = ", ".join(sel[:10]) if sel else "（无）"
        return (
            f"- 批次 #{prior.get('batch_index', '?')}：{confirmed}，"
            f"severity={verdict.get('severity', 'none')}，"
            f"模式={verdict.get('threat_pattern', 'none')}；"
            f"覆盖 trace {prior.get('from_trace_id', 0)}→{prior.get('to_trace_id', 0)}，"
            f"复核 {prior.get('sessions_scanned', 0)} 会话（{sel_str}）。"
            f"结论：{prior.get('summary') or verdict.get('evidence', '')}"
        )

    async def _load_session_intents(
        self, session_ids: set[str], max_trace_id: int,
    ) -> dict[str, dict]:
        """加载各会话"截至本批最后一跳"的累积意图基准。

        每个会话独立取自己的意图流——不跨会话、不用全局意图。
        只取 ``source.trace_id <= max_trace_id`` 的 Δ：排除"在本批这些跳之后用户才更新的
        意图"——新意图不应溯及既往地用到之前已发生的跳上。
        """
        intents: dict[str, dict] = {}
        for sid in session_ids:
            if not sid:
                continue
            vs = await self._tracer.storage.load_vertical_state(sid)
            try:
                revisions = json.loads((vs or {}).get("intent_revisions_json") or "[]")
            except (json.JSONDecodeError, TypeError):
                revisions = []
            applicable = [
                r for r in revisions
                if (r.get("source") or {}).get("trace_id", 0) <= max_trace_id
            ]
            intents[sid] = self._accumulate_intent(applicable)
        return intents

    @staticmethod
    def _accumulate_intent(revisions: list[dict]) -> dict:
        """把（调用方已按时间过滤的）意图增量 Δ 累积成基准。

        抽取是增量的（每条 Δ 只含本条 U2A 的新增 goal/constraints/prohibitions，
        见 vertical/prompts.py 的 INTENT_REVISION_PROMPT），所以"截至某时刻的完整意图"
        = 该时刻之前所有 Δ 的并集（prohibitions/constraints 取并、goal 取最新非空）——
        只取末条 Δ 会漏，取全部 Δ 会把之后的更新溯及既往（由调用方按 max_trace_id 过滤）。
        """
        goals: list[str] = []
        constraints: set[str] = set()
        prohibitions: set[str] = set()
        for r in revisions or []:
            if r.get("goal"):
                goals.append(r["goal"])
            for c in r.get("constraints") or []:
                constraints.add(c)
            for p in r.get("prohibitions") or []:
                prohibitions.add(p)
        return {
            "goal": goals[-1] if goals else "",
            "constraints": sorted(constraints),
            "prohibitions": sorted(prohibitions),
        }

    @staticmethod
    def _build_sessions_data(
        traces: list[dict],
        hop_scores: list[dict],
        selected: set[str],
        w_map: dict[str, float],
        intents: dict[str, dict] | None = None,
    ) -> list[dict]:
        """为选中的会话构建确认画像：每会话 top 高分跳（含内容）+ 累积意图基准。"""
        intents = intents or {}
        content_by_trace: dict[int, str] = {}
        for t in traces:
            tid = t.get("id")
            if tid is not None:
                content_by_trace[tid] = t.get("content", "")

        per_session: dict[str, list[dict]] = {}
        for h in hop_scores:
            sid = h.get("session_id", "")
            if sid not in selected:
                continue
            per_session.setdefault(sid, []).append({
                "trace_id": h.get("trace_id", 0),
                "score": h.get("score", 0.0),
                "severity": h.get("severity", "none"),
                "deviation_type": h.get("deviation_type", "none"),
                "field_type": h.get("field_type", ""),
                "content": content_by_trace.get(h.get("trace_id", 0), ""),
            })

        sessions_data: list[dict] = []
        for sid, hops in per_session.items():
            hops.sort(key=lambda x: x.get("score", 0.0), reverse=True)
            sessions_data.append({
                "session_id": sid,
                "w_value": w_map.get(sid, 0.0),
                "intent": intents.get(sid, {}),
                "hops": hops,
            })
        sessions_data.sort(key=lambda x: x["w_value"], reverse=True)
        return sessions_data

    @staticmethod
    def _derive_overall(verdict: ConfirmationVerdict) -> str:
        """由确认结论推导 overall_verdict。"""
        if not verdict.confirmed:
            return "clean"
        rank = SEVERITY_RANK.get(verdict.severity, 0)
        if rank >= SEVERITY_RANK["high"]:
            return "malicious"
        return "suspicious"

    # ------------------------------------------------------------------
    # 异步任务管理
    # ------------------------------------------------------------------

    async def trigger_analysis_async(self, did: str, triggered_by: str = "manual") -> dict:
        """fire-and-forget 确认任务。"""
        if did in self._running_tasks and not self._running_tasks[did].done():
            return {"triggered": True, "status": "already_running", "did": did}

        async def _task_body():
            try:
                async with self._get_lock(did):
                    result = await self.run_analysis(did, triggered_by=triggered_by)
                return result
            except Exception as e:
                logger.error("Async horizontal confirm failed for did={}: {}", did, e)
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
        if did in self._task_results:
            result = self._task_results.pop(did)
            return {"status": "completed", **result.to_dict()}
        if did in self._running_tasks and not self._running_tasks[did].done():
            return {
                "status": "running",
                "phase": self._task_phases.get(did, "unknown"),
                "did": did,
            }
        return {"status": "not_found", "did": did}

    async def shutdown(self) -> None:
        tasks = list(self._running_tasks.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._running_tasks.clear()
        self._locks.clear()
        self._task_phases.clear()

    # ------------------------------------------------------------------
    # 告警
    # ------------------------------------------------------------------

    async def _notify_confirmed(
        self, did: str, verdict: ConfirmationVerdict, report_row_id: int,
    ) -> None:
        """确认存在跨会话攻击 → 写 malicious_reports(source=horizontal_analysis)。"""
        logger.warning(
            "Horizontal confirmed: did={}, severity={}, score={}, pattern={}",
            did, verdict.severity, verdict.taint_score, verdict.threat_pattern,
        )
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
            "raw_evidence": {
                "evidence_items": [e.to_dict() for e in verdict.evidence_items],
                "selected_sessions": verdict.sessions_reviewed,
            },
            "timestamp": 0.0,
        })
