"""ProtocolSession — 协议节点层 per-session 验证状态 + 分析状态容器。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .pending_message import PendingMessage


@dataclass
class ProtocolSession:
    """协议节点层 session：管理 nonce 暂存、hop 序列校验、分析状态。"""

    key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    # -- nonce-based pending message storage --

    def store_pending_message(self, nonce: str, msg: PendingMessage) -> None:
        """暂存 PendingMessage，以 nonce 为 key。"""
        self.metadata[f"_pending:{nonce}"] = msg.to_dict()
        self.updated_at = time.time()

    def get_pending_message(self, nonce: str) -> PendingMessage | None:
        """检索 PendingMessage，过期则自动清理。"""
        data = self.metadata.get(f"_pending:{nonce}")
        if not data:
            return None
        msg = PendingMessage.from_dict(data)
        if msg.is_expired():
            self.remove_pending_message(nonce)
            return None
        return msg

    def remove_pending_message(self, nonce: str) -> None:
        """移除指定 nonce 的 PendingMessage。"""
        self.metadata.pop(f"_pending:{nonce}", None)

    # -- hop count validation state --

    def get_last_completed_hop_count(self) -> int | None:
        return self.metadata.get("LastCompletedHopCount")

    def set_last_completed_hop_count(self, hc: int) -> None:
        self.metadata["LastCompletedHopCount"] = hc
        self.updated_at = time.time()

    # -- generic metadata (for _pending_intent_content, _intent_retry_count, etc.) --

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self.updated_at = time.time()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    # -- Analysis state tracking --

    def get_analysis_state(self) -> dict[str, Any]:
        """Get analysis-related state from metadata."""
        return {
            "report_count": self.metadata.get("_analysis_report_count", 0),
            "last_trace_id": self.metadata.get("_analysis_last_trace_id", 0),
            "batch_index": self.metadata.get("_analysis_batch_index", 0),
            "context": self.metadata.get("_analysis_context", ""),
            "intent": self.metadata.get("_analysis_intent"),
        }

    def increment_report_count(self) -> int:
        """Increment and return the unchecked report count."""
        count = self.metadata.get("_analysis_report_count", 0) + 1
        self.metadata["_analysis_report_count"] = count
        self.updated_at = time.time()
        return count

    def reset_report_count(self) -> None:
        """Reset the unchecked report count to 0."""
        self.metadata["_analysis_report_count"] = 0
        self.updated_at = time.time()

    def update_analysis_cursor(
        self, batch_index: int, last_trace_id: int, context: str,
    ) -> None:
        """Update the analysis cursor after a successful analysis run."""
        self.metadata["_analysis_batch_index"] = batch_index
        self.metadata["_analysis_last_trace_id"] = last_trace_id
        self.metadata["_analysis_context"] = context
        self.updated_at = time.time()

    def set_intent(self, intent: dict) -> None:
        """Store extracted intent descriptor."""
        self.metadata["_analysis_intent"] = intent
        self.updated_at = time.time()

    def get_intent(self) -> dict | None:
        """Retrieve stored intent descriptor, if any."""
        return self.metadata.get("_analysis_intent")
