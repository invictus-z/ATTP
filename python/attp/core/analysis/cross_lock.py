"""Cross-Lock Coordinator — 十字锁定协调器。

串联纵向分析（纵轴）与横向分析（横轴）的顶层编排。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from attp.app.logging import get_logger

if TYPE_CHECKING:
    from attp.core.analysis.vertical.orchestrator import VerticalOrchestrator
    from attp.core.analysis.horizontal.orchestrator import HorizontalOrchestrator

logger = get_logger("CrossLock")


class CrossLockCoordinator:
    """十字锁定协调器 — 串联纵向分析与横向分析的触发关系。

    Usage::

        coordinator = CrossLockCoordinator(vertical_orch, horizontal_orch)
        # 替代原 orchestrator 注入到 ProtocolPort
        port.set_orchestrator(coordinator)
    """

    def __init__(
        self,
        vertical_orchestrator: VerticalOrchestrator,
        horizontal_orchestrator: HorizontalOrchestrator | None = None,
    ):
        self._vertical = vertical_orchestrator
        self._horizontal = horizontal_orchestrator

        # Wire the horizontal trigger callback into vertical orchestrator
        if self._horizontal is not None:
            self._vertical._horizontal_trigger_callback = self._on_vertical_done
            logger.info("Cross-Lock: 纵横联动已激活")

    # ------------------------------------------------------------------
    # Cross-Lock internal bridge
    # ------------------------------------------------------------------

    async def _on_vertical_done(self, did: str, session_id: str) -> None:
        """纵向分析完成后的横轴累积入口。"""
        if self._horizontal is None:
            return
        result = await self._horizontal.on_vertical_analysis_completed(did, session_id)
        if result.get("triggered"):
            logger.info(
                "Cross-Lock: 横向分析自动触发 did={}, pending={}/{}",
                did, result["pending_count"], result["threshold"],
            )

    # ------------------------------------------------------------------
    # 对外接口 — 纵向分析委托
    # ------------------------------------------------------------------

    async def on_field_U2A_recorded(self, session_id: str, content: str) -> None:
        """U2A 到达 → 委托纵向编排器。"""
        await self._vertical.on_field_U2A_recorded(session_id, content)

    async def on_record_received(self, session_id: str) -> None:
        """每条 record → 委托纵向编排器。"""
        await self._vertical.on_record_received(session_id)

    async def trigger_analysis_async(self, session_id: str) -> dict:
        """手动触发纵向分析。"""
        return await self._vertical.trigger_analysis_async(session_id)

    def get_analysis_status(self, session_id: str) -> dict:
        """查询纵向分析状态。"""
        return self._vertical.get_analysis_status(session_id)

    # ------------------------------------------------------------------
    # 对外接口 — 横向分析委托
    # ------------------------------------------------------------------

    async def trigger_horizontal_async(self, did: str) -> dict:
        """手动触发横向分析。"""
        if self._horizontal is None:
            return {"triggered": False, "reason": "horizontal_disabled"}
        return await self._horizontal.trigger_analysis_async(did)

    def get_horizontal_status(self, did: str) -> dict:
        """查询横向分析状态。"""
        if self._horizontal is None:
            return {"status": "not_found", "did": did, "reason": "horizontal_disabled"}
        return self._horizontal.get_analysis_status(did)

    # ------------------------------------------------------------------
    # 综合状态
    # ------------------------------------------------------------------

    @property
    def vertical(self) -> VerticalOrchestrator:
        return self._vertical

    @property
    def horizontal(self) -> HorizontalOrchestrator | None:
        return self._horizontal
