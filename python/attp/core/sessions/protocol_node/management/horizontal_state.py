"""Horizontal Analysis State Manager — 横向分析状态管理（per-DID 全局）。

管理每个 DID 的横向累积计数器和分析游标。
横向状态是全局 per-DID 的，不属于任何单个 Session。
持久化到 horizontal_analysis_states 表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from attp.app.logging import get_logger

if TYPE_CHECKING:
    from attp.core.storage import SqliteStore

logger = get_logger("HorizontalState")


@dataclass
class HorizontalAccumulationState:
    """Per-DID 横向分析累积状态。"""
    did: str
    node_type: str = "agent"
    accumulated_count: int = 0
    last_trace_id: int = 0
    batch_index: int = 0
    context: str = ""


class HorizontalAnalysisManager:
    """横向分析状态管理 — per-DID 的全局累积状态。"""

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
                    state.accumulated_count = saved.get("accumulated_count", 0)
                    state.last_trace_id = saved.get("last_trace_id", 0)
                    state.batch_index = saved.get("batch_index", 0)
                    state.context = saved.get("context", "")
                self._restored_dids.add(did)
            self._states[did] = state
        return self._states[did]

    async def restore_state(self, did: str) -> None:
        """从 SQLite 恢复 DID 的横向状态。"""
        await self._ensure_loaded(did)

    async def increment_accumulation(self, did: str) -> int:
        """累加 DID 的横向计数器。返回累加后的值。"""
        state = await self._ensure_loaded(did)
        state.accumulated_count += 1
        await self._persist(did)
        return state.accumulated_count

    async def reset_accumulation(self, did: str) -> None:
        """重置 DID 的横向计数器。"""
        state = await self._ensure_loaded(did)
        state.accumulated_count = 0
        await self._persist(did)

    async def get_cursor(self, did: str) -> dict:
        """获取 DID 的横向分析游标。"""
        state = await self._ensure_loaded(did)
        return {
            "last_trace_id": state.last_trace_id,
            "batch_index": state.batch_index,
            "context": state.context,
            "accumulated_count": state.accumulated_count,
        }

    async def update_cursor(
        self, did: str, batch_index: int, last_trace_id: int, context: str, node_type: str = "",
    ) -> None:
        """更新 DID 的横向分析游标。"""
        state = await self._ensure_loaded(did)
        state.batch_index = batch_index
        state.last_trace_id = last_trace_id
        state.context = context
        if node_type:
            state.node_type = node_type
        await self._persist(did)

    async def _persist(self, did: str) -> None:
        """持久化 DID 状态到 SQLite。"""
        state = self._states.get(did)
        if not state:
            return
        await self._storage.save_horizontal_state(did, {
            "node_type": state.node_type,
            "accumulated_count": state.accumulated_count,
            "last_trace_id": state.last_trace_id,
            "batch_index": state.batch_index,
            "context": state.context,
        })
