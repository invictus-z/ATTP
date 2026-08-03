"""Cross-Lock Coordinator — 十字锁定协调器（逐跳改版）。

串联纵轴（逐跳评分）与横轴（per-DID F 累加 + 跨会话确认）：
- 纵轴每打一跳分 → 回调 ``horizontal.on_hop_scored`` 喂入 F；
- F > R_S → 横轴自动确认。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attp.app.logging import get_logger

if TYPE_CHECKING:
    from attp.core.analysis.vertical.orchestrator import VerticalOrchestrator
    from attp.core.analysis.horizontal.orchestrator import HorizontalOrchestrator

logger = get_logger("CrossLock")


class CrossLockCoordinator:
    """十字锁定协调器 — 串联纵轴逐跳评分与横轴 F 累加/确认。

    Usage::

        coordinator = CrossLockCoordinator(vertical_orch, horizontal_orch)
        port.set_orchestrator(coordinator)
        # /record 落库后：await coordinator.enqueue_trace(session_id, trace_id)
    """

    def __init__(
        self,
        vertical_orchestrator: VerticalOrchestrator,
        horizontal_orchestrator: HorizontalOrchestrator | None = None,
    ):
        self._vertical = vertical_orchestrator
        self._horizontal = horizontal_orchestrator

        # 把横轴 F 累加回调注入纵轴
        if self._horizontal is not None:
            self._vertical._on_hop_scored_callback = self._on_hop_scored
            logger.info("Cross-Lock: 纵横联动已激活（逐跳 F 累加）")

    # ------------------------------------------------------------------
    # 内部桥接
    # ------------------------------------------------------------------

    async def _on_hop_scored(
        self, did: str, session_id: str, trace_id: int, score: float, field_type: str,
    ) -> None:
        if self._horizontal is None:
            return
        await self._horizontal.on_hop_scored(did, session_id, trace_id, score, field_type)

    # ------------------------------------------------------------------
    # 对外接口 — 纵轴委托
    # ------------------------------------------------------------------

    async def enqueue_trace(self, session_id: str, hop: dict) -> None:
        """/record 落库后调用：把该跳投进会话的有界队列（不阻塞）。"""
        await self._vertical.enqueue_trace(session_id, hop)

    async def trigger_analysis_async(self, session_id: str) -> dict:
        """手动触发纵轴（补打未评分跳）。"""
        return await self._vertical.trigger_analysis_async(session_id)

    def get_analysis_status(self, session_id: str) -> dict:
        """查询纵轴 worker 状态。"""
        return self._vertical.get_analysis_status(session_id)

    # ------------------------------------------------------------------
    # 对外接口 — 横轴委托
    # ------------------------------------------------------------------

    async def trigger_horizontal_async(self, did: str) -> dict:
        """手动触发横轴确认。"""
        if self._horizontal is None:
            return {"triggered": False, "reason": "horizontal_disabled"}
        return await self._horizontal.trigger_analysis_async(did)

    @property
    def r_s(self) -> float | None:
        """横轴 F 累积阈值 R_S（供 /h/state 返回，使前端进度条与后端一致）。
        横轴未启用时为 None。"""
        return self._horizontal._r_s if self._horizontal is not None else None

    def get_horizontal_status(self, did: str) -> dict:
        """查询横轴确认状态。"""
        if self._horizontal is None:
            return {"status": "not_found", "did": did, "reason": "horizontal_disabled"}
        return self._horizontal.get_analysis_status(did)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """停止纵横 worker（ProtocolNode.stop 调用）。"""
        await self._vertical.shutdown()
        if self._horizontal is not None:
            await self._horizontal.shutdown()

    @property
    def vertical(self) -> VerticalOrchestrator:
        return self._vertical

    @property
    def horizontal(self) -> HorizontalOrchestrator | None:
        return self._horizontal
