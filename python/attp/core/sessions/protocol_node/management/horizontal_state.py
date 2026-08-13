"""Horizontal Analysis State Manager — 横向分析状态管理（per-DID 全局，逐跳改版）。

管理每个 DID 的累积偏离 F、体积计数、确认游标（last_trace_id）、批次与上下文。
F 跨会话叠加：纵轴每打一跳分即调用 ``accumulate`` 喂入；达阈值触发横轴确认，
确认后 ``close`` 重置 F/体积并推进游标（闭案）。持久化到 horizontal_analysis_states 表。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from attp.app.logging import get_logger

if TYPE_CHECKING:
    from attp.core.storage import SqliteStore

logger = get_logger("HorizontalState")


@dataclass
class HorizontalAccumulationState:
    """Per-DID 横向累积状态（F 跨会话叠加）。

    字段语义：
        f_value       — 累积偏离 F_d = Σ s_j³（三次方和，无折扣/死区）
        volume        — 自上次闭案以来的 hop 计数（观测用，不再触发确认）
        last_trace_id — 确认游标（已闭案到此 trace_id）
        batch_index   — 已完成的确认次数（每确认一次 +1）
        context       — 最近一次确认的摘要（节点档案）
    """

    did: str
    node_type: str = "agent"
    f_value: float = 0.0
    volume: int = 0
    last_trace_id: int = 0
    batch_index: int = 0
    context: str = ""


class HorizontalAnalysisManager:
    """横向分析状态管理 — per-DID 的 F 累加与闭案。"""

    def __init__(self, storage: SqliteStore):
        self._storage = storage
        self._states: dict[str, HorizontalAccumulationState] = {}
        self._restored_dids: set[str] = set()

    async def _ensure_loaded(self, did: str) -> HorizontalAccumulationState:
        """确保 DID 状态已从 SQLite 加载。"""
        if did not in self._states:
            state = HorizontalAccumulationState(did=did)
            if did not in self._restored_dids:
                saved = await self._storage.load_horizontal_state(did)
                if saved:
                    state.node_type = saved.get("node_type", "agent")
                    state.f_value = saved.get("f_value", 0.0)
                    state.volume = saved.get("volume", 0)
                    state.last_trace_id = saved.get("last_trace_id", 0)
                    state.batch_index = saved.get("batch_index", 0)
                    state.context = saved.get("context", "")
                self._restored_dids.add(did)
            self._states[did] = state
        return self._states[did]

    async def restore_state(self, did: str) -> None:
        """从 SQLite 恢复 DID 的横向状态。"""
        await self._ensure_loaded(did)

    async def accumulate(
        self, did: str, f_delta: float, node_type: str = "",
    ) -> tuple[float, int]:
        """累加一条 hop 的偏离增量到 F_d，volume+1，持久化。

        三次方和累加：F_i = F_{i-1} + s_i³（无折扣 γ、无死区 d）。
        F 单调递增，分散小偏移终将超过 R_S 触发确认。

        Args:
            did: 发送方 DID。
            f_delta: 本跳对 F 的贡献 s_i³（调用方已算好）。
            node_type: 该 DID 的节点类型（首次见到时记录）。

        Returns:
            (累加后的 f_value, 累加后的 volume)。
        """
        state = await self._ensure_loaded(did)
        state.f_value += f_delta
        state.volume += 1
        if node_type:
            state.node_type = node_type
        await self._persist(did)
        return state.f_value, state.volume

    async def close(self, did: str, advance_cursor_to: int, context: str = "") -> None:
        """闭案：重置 F/体积、推进确认游标、batch+1、记录摘要。"""
        state = await self._ensure_loaded(did)
        state.f_value = 0.0
        state.volume = 0
        if advance_cursor_to > state.last_trace_id:
            state.last_trace_id = advance_cursor_to
        state.batch_index += 1
        if context:
            state.context = context
        await self._persist(did)

    async def reset_accumulation(self, did: str) -> None:
        """清零 F/体积，但不动游标/batch/context。

        用于 no_new_scores：滞留的 F 来自游标已越过的晚到跳（不会再被确认），
        清掉避免反复空触发；这些跳的纵轴 R_T 告警已发。
        """
        state = await self._ensure_loaded(did)
        state.f_value = 0.0
        state.volume = 0
        await self._persist(did)

    async def get_state(self, did: str) -> dict:
        """获取 DID 的横向累积状态。"""
        state = await self._ensure_loaded(did)
        return {
            "node_type": state.node_type,
            "f_value": state.f_value,
            "volume": state.volume,
            "last_trace_id": state.last_trace_id,
            "batch_index": state.batch_index,
            "context": state.context,
        }

    async def get_cursor(self, did: str) -> int:
        state = await self._ensure_loaded(did)
        return state.last_trace_id

    async def _persist(self, did: str) -> None:
        """持久化 DID 状态到 SQLite。"""
        state = self._states.get(did)
        if not state:
            return
        await self._storage.save_horizontal_state(did, {
            "node_type": state.node_type,
            "f_value": state.f_value,
            "volume": state.volume,
            "last_trace_id": state.last_trace_id,
            "batch_index": state.batch_index,
            "context": state.context,
        })
