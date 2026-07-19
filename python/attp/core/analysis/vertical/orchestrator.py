"""Vertical Axis — 纵向逐跳编排器（per-session 有界队列 worker）。

改版核心：``/record`` 落库后把该跳 ``hop`` 投进该会话的**有界队列**即返回
（不 await LLM）；每个会话一个后台 worker 从队列消费，按 trace 序串行
（per-session asyncio.Lock 保护意图流 / 隐状态 / 游标），LLM 调用受全局
信号量 ``concurrency`` 限并发（即「同时处理的 hop 数」）。

队列满（``queue_maxsize``）= 真背压：``/record`` 不阻塞，溢出的 hop 留在 DB，
由 worker 的 **catch-up 扫描**（启动时 / 空闲时 / 手动触发）按游标补打，不丢数据。

分流（§2）：
- U2A 且 sender==发起者 DID → 抽 Δ 追加意图流（**不打分**）。
- U2A 但 sender≠发起者 DID → **当普通动作跳打分**（防第二用户注入/越权引导盲区）。
- 动作跳（A2A/A2T/T2A/A2U）→ V-Reasoner 逐跳打分 → 落 hop_score → 更新 h_i →
  ``s_i > R_T`` 立即告警 → 把 **sub-R_T** 的 ``s_i`` 报给横轴 ``on_hop_scored``（critical
  不重复计入 F：R_T 抓单跳恶，F 抓累积慢投毒）。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from attp.app.logging import get_logger
from attp.core.analysis.vertical.analyzer import FIELD_TYPE_TO_SENDER_NODE_TYPE
from attp.core.sse import EventType, Topic

if TYPE_CHECKING:
    from attp.core.analysis.base_models import IntentRevisionSource
    from attp.core.analysis.vertical.analyzer import VerticalIntentAnalyzer
    from attp.core.sessions.protocol_node.management.vertical_state import VerticalAnalysisManager
    from attp.core.sse import EventBroker
    from attp.core.pn_tracer import ProtocolTracer

logger = get_logger("VerticalAnalysis")

#: worker 空闲超时（秒）：队列空且无新增即退出，下次 enqueue 重建。
WORKER_IDLE_TIMEOUT = 300.0

#: 投进队列的"补打"哨兵：worker 见到它就跑一次 catch-up 扫描（手动触发用）。
_CATCHUP_SENTINEL: Any = object()


class VerticalOrchestrator:
    """逐跳纵向编排：per-session 有界队列 worker + 全局并发限流。"""

    def __init__(
        self,
        analyzer: VerticalIntentAnalyzer,
        vertical_state_mgr: VerticalAnalysisManager,
        tracer: ProtocolTracer,
        r_t: float = 7.5,
        concurrency: int = 8,
        queue_maxsize: int = 1000,
        event_broker: EventBroker | None = None,
    ):
        self._analyzer = analyzer
        self._state_mgr = vertical_state_mgr
        self._tracer = tracer
        self._r_t = r_t
        self._queue_maxsize = queue_maxsize
        self._broker = event_broker
        # 同时处理的 hop 数（并发上限）：每个 worker 处理一跳前先获取此信号量。
        self._sem = asyncio.Semaphore(concurrency)

        self._workers: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._phases: dict[str, str] = {}

        # 由 CrossLockCoordinator 注入：每打一跳分即回报横轴（F 累加）
        self._on_hop_scored_callback: (
            Callable[[str, str, int, float, str], Awaitable[None]] | None
        ) = None

    # ------------------------------------------------------------------
    # 公开接口（/record、手动触发、状态查询）
    # ------------------------------------------------------------------

    async def enqueue_trace(self, session_id: str, hop: dict) -> None:
        """``/record`` 落库后调用：把该跳投进会话的有界队列（不阻塞、不等 LLM）。

        队列满时 ``/record`` 仍不阻塞——该 hop 已在 DB，由 worker 的 catch-up
        扫描（空闲/手动触发）按游标补打，不丢数据。
        """
        self._ensure_worker(session_id)
        queue = self._queues[session_id]
        try:
            queue.put_nowait(hop)
        except asyncio.QueueFull:
            logger.warning(
                "Vertical queue full (session={}, cap={}); hop trace={} 留在 DB，"
                "将由 catch-up 扫描补打",
                session_id, self._queue_maxsize, hop.get("trace_id"),
            )

    async def trigger_analysis_async(self, session_id: str) -> dict:
        """手动触发：确保该会话当前未打分的 hop 被消费（投哨兵触发 catch-up 扫描）。"""
        await self._state_mgr.restore_state(session_id)
        self._ensure_worker(session_id)
        try:
            self._queues[session_id].put_nowait(_CATCHUP_SENTINEL)
        except asyncio.QueueFull:
            # 队列满说明 worker 还在忙，忙完空闲时会自动 catch-up 扫描
            pass
        return {"triggered": True, "status": "running", "session_id": session_id}

    def get_analysis_status(self, session_id: str) -> dict:
        """查询 worker 阶段与队列深度（供 /llm-status 轮询）。"""
        if session_id in self._workers and not self._workers[session_id].done():
            queue = self._queues.get(session_id)
            return {
                "status": "running",
                "phase": self._phases.get(session_id, "idle"),
                "queue_depth": queue.qsize() if queue else 0,
                "session_id": session_id,
            }
        return {"status": "idle", "session_id": session_id}

    async def shutdown(self) -> None:
        """停止所有 worker（ProtocolNode.stop 调用）。"""
        tasks = list(self._workers.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()
        self._queues.clear()
        self._locks.clear()
        self._phases.clear()

    # ------------------------------------------------------------------
    # worker 生命周期
    # ------------------------------------------------------------------

    def _ensure_worker(self, session_id: str) -> None:
        if session_id in self._workers and not self._workers[session_id].done():
            return
        self._queues.setdefault(
            session_id, asyncio.Queue(maxsize=self._queue_maxsize),
        )
        self._locks.setdefault(session_id, asyncio.Lock())
        task = asyncio.create_task(self._worker_loop(session_id))
        self._workers[session_id] = task

    async def _worker_loop(self, session_id: str) -> None:
        queue = self._queues[session_id]
        lock = self._locks[session_id]
        try:
            # 启动即 catch-up：恢复崩溃前已落库但未打分的跳
            async with lock:
                await self._catchup_scan(session_id)

            while True:
                self._phases[session_id] = "idle"
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=WORKER_IDLE_TIMEOUT)
                except asyncio.TimeoutError:
                    # 空闲：补打溢出/残留，仍无新增则退出 worker（下次 enqueue 重建）
                    async with lock:
                        got = await self._catchup_scan(session_id)
                    if not got:
                        logger.debug(
                            "Vertical worker idle-timeout, exiting: session={}", session_id,
                        )
                        break
                    continue

                if item is _CATCHUP_SENTINEL:
                    async with lock:
                        await self._catchup_scan(session_id)
                    continue

                # 普通跳：按游标去重（catch-up 可能已处理过），再串行处理
                hop = item
                cursor = (await self._state_mgr.get_state(session_id))["last_scored_trace_id"]
                if hop.get("trace_id", 0) <= cursor:
                    continue
                self._phases[session_id] = "scoring"
                async with lock:
                    await self._process_one(session_id, hop)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Vertical worker crashed for session={}: {}", session_id, e)
        finally:
            self._workers.pop(session_id, None)
            self._phases.pop(session_id, None)

    # ------------------------------------------------------------------
    # 逐跳处理
    # ------------------------------------------------------------------

    async def _catchup_scan(self, session_id: str) -> bool:
        """从游标补打所有未处理的 trace（恢复 / 溢出 / 残留）。返回是否处理了任何跳。"""
        state = await self._state_mgr.get_state(session_id)
        cursor = state["last_scored_trace_id"]
        traces, _max_id = await self._tracer.recover_traces_since(session_id, cursor)
        if not traces:
            return False
        for trace in traces:
            await self._process_one(session_id, self._hop_from_row(trace))
        return True

    @staticmethod
    def _hop_from_row(trace: dict) -> dict:
        """把 behavior_traces 行整理成统一的 hop dict（供 _process_one）。"""
        return {
            "trace_id": trace.get("id", 0),
            "session_id": trace.get("session_id", ""),
            "sender_did": trace.get("sender_did") or trace.get("node_did", ""),
            "field_type": trace.get("field_type", ""),
            "hop_count": trace.get("hop_count", [0, 0]),
            "content": trace.get("content", ""),
            "target": trace.get("target_did") or trace.get("target", ""),
            "timestamp": trace.get("timestamp", 0.0),
        }

    async def _process_one(self, session_id: str, hop: dict) -> None:
        """处理单跳：分流 + 推进游标（成功或失败都推进，避免卡死）。"""
        trace_id = hop.get("trace_id", 0)
        try:
            if hop.get("field_type") == "U2A":
                await self._handle_u2a(session_id, hop)
            else:
                await self._handle_action(session_id, hop)
        except Exception as e:
            logger.error(
                "Vertical hop processing failed (session={}, trace={}): {}",
                session_id, trace_id, e,
            )
        finally:
            # 即使失败也推进游标（失败/降级本次不做，不重试）
            await self._state_mgr.advance_score_cursor(session_id, trace_id)

    async def _handle_u2a(self, session_id: str, hop: dict) -> None:
        """U2A 处理：发起者→抽 Δ 追加意图流（不打分）；非发起者→当普通动作跳打分。

        非发起者 U2A 不采信为意图（防伪造"用户说…"），但作为可疑行为照常打分——
        第二个用户中途注入/越权引导是典型的 d3 注入向量，直接丢弃会留盲区。
        """
        state = await self._state_mgr.get_state(session_id)
        initiator = state["initiator_did"]
        sender_did = hop["sender_did"]
        if not initiator:
            await self._state_mgr.set_initiator_did(session_id, sender_did)
            initiator = sender_did
        if sender_did != initiator:
            # 非发起者 U2A：不进意图流，但照常打分（可能 d3 注入 / d2 越权引导）
            await self._handle_action(session_id, hop)
            return

        from attp.core.analysis.base_models import IntentRevisionSource

        source = IntentRevisionSource(
            trace_id=hop["trace_id"], did=sender_did, timestamp=hop["timestamp"],
        )
        async with self._sem:
            revision = await self._analyzer.extract_intent_revision(
                hop["content"], state["intent_revisions"], source=source,
            )
        await self._state_mgr.append_intent_revision(session_id, revision.to_dict())

        if self._broker:
            await self._broker.publish(
                EventType.ANALYSIS_PROGRESS,
                {"axis": "vertical", "session_id": session_id,
                 "phase": "intent_appended", "trace_id": hop["trace_id"]},
                topic=Topic.ANALYSIS,
            )

    async def _handle_action(self, session_id: str, hop: dict) -> None:
        """动作跳 → V-Reasoner 打分 → 落库 → 更新 h → R_T 告警 →（仅 sub-R_T）报横轴。"""
        state = await self._state_mgr.get_state(session_id)
        intent_snapshot = state["intent_revisions"]
        hidden_prev = state["hidden_state"]

        async with self._sem:
            score = await self._analyzer.score_hop(hop, intent_snapshot, hidden_prev)

        if score is None:
            return  # 评分失败，本次不做（cursor 已由调用方推进）

        await self._tracer.save_hop_score(self._hop_score_to_row(score))

        if score.hidden_state:
            await self._state_mgr.set_hidden_state(session_id, score.hidden_state)

        # R_T：单点立即告警
        if score.score > self._r_t:
            await self._notify_rt_alert(session_id, score)

        # 报给横轴（F 累加）——仅 sub-R_T 的跳：R_T 命中的单点恶已由上面告警，
        # 不再喂横轴 F（轴职责分离：R_T 抓单跳恶，F 抓 sub-R_T 累积的慢投毒；
        # critical 重复计入只会让 F 爆炸、横轴报告与 R_T 重复）。
        if self._on_hop_scored_callback and score.score <= self._r_t:
            try:
                await self._on_hop_scored_callback(
                    score.sender_did, session_id, score.trace_id,
                    score.score, score.field_type,
                )
            except Exception as e:
                logger.error(
                    "on_hop_scored callback failed (did={}, trace={}): {}",
                    score.sender_did, score.trace_id, e,
                )

    # ------------------------------------------------------------------
    # R_T 告警
    # ------------------------------------------------------------------

    async def _notify_rt_alert(self, session_id: str, score) -> None:
        """单点 R_T 告警：写 malicious_reports(source=vertical_analysis)。"""
        node_type = FIELD_TYPE_TO_SENDER_NODE_TYPE.get(score.field_type, "agent")
        evidence_desc = " | ".join(
            e.description for e in score.evidence_items if e.description
        ) or f"单跳评分 {score.score} 超过 R_T={self._r_t}（{score.deviation_type}）"

        await self._tracer.storage.save_malicious_report({
            "source": "vertical_analysis",
            "target_did": score.sender_did,
            "node_type": node_type,
            "session_id": session_id,
            "evidence_type": score.deviation_type,
            "severity": score.severity,
            "taint_score": score.score,
            "evidence_description": evidence_desc,
            "nonce": "",
            "report_id": None,
            "raw_evidence": {
                "trace_id": score.trace_id,
                "dimensions": score.dimensions,
                "breadth": score.breadth,
                "evidence_items": [e.to_dict() for e in score.evidence_items],
            },
            "timestamp": score.timestamp,
        })
        logger.warning(
            "Vertical R_T alert: session={}, did={}, trace={}, score={}, severity={}",
            session_id, score.sender_did, score.trace_id, score.score, score.severity,
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hop_score_to_row(score) -> dict:
        dims = score.dimensions or [0.0, 0.0, 0.0, 0.0]
        while len(dims) < 4:
            dims.append(0.0)
        return {
            "trace_id": score.trace_id,
            "session_id": score.session_id,
            "sender_did": score.sender_did,
            "field_type": score.field_type,
            "hop_count": list(score.hop_count),
            "score": score.score,
            "dim1": dims[0], "dim2": dims[1], "dim3": dims[2], "dim4": dims[3],
            "breadth": score.breadth,
            "severity": score.severity,
            "deviation_type": score.deviation_type,
            "evidence_refs": [e.to_dict() for e in score.evidence_items],
            "hidden_state": score.hidden_state,
            "timestamp": score.timestamp,
        }
