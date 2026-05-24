"""ProtocolSession — 协议节点层 per-session 验证状态 + 分析状态容器。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .pending_message import PendingMessage


@dataclass
class AnalysisState:
    """语义分析状态 — report 计数、游标、intent。"""

    report_count: int = 0
    last_trace_id: int = 0
    batch_index: int = 0
    context: str = ""
    intent: dict | None = None


@dataclass
class ProtocolSession:
    """协议节点层 session：管理 nonce 暂存、hop 序列校验、分析状态。"""

    key: str
    updated_at: float = field(default_factory=time.time)

    # -- 消息验证状态 --
    pending_messages: dict[str, PendingMessage] = field(default_factory=dict)
    completed_nonces: list[str] = field(default_factory=list)
    hop_count_map: dict[int, int] = field(default_factory=dict)

    # -- 可信名单 --
    trusted_did_list: list[str] = field(default_factory=list)

    # -- 分析状态 --
    analysis: AnalysisState = field(default_factory=AnalysisState)

    # -- 通用元数据（仅用于动态数据，如 _pending_intent_content） --
    metadata: dict[str, Any] = field(default_factory=dict)

    # ================================================================
    # Pending message management
    # ================================================================

    def store_pending_message(self, nonce: str, msg: PendingMessage) -> None:
        self.pending_messages[nonce] = msg
        self.updated_at = time.time()

    def get_pending_message(self, nonce: str) -> PendingMessage | None:
        msg = self.pending_messages.get(nonce)
        if not msg:
            return None
        if msg.is_expired():
            self.remove_pending_message(nonce)
            return None
        return msg

    def remove_pending_message(self, nonce: str) -> None:
        self.pending_messages.pop(nonce, None)

    def pop_expired_pending_messages(self) -> list[tuple[str, PendingMessage]]:
        """取出所有已过期的 PendingMessage，从 session 中移除并返回。"""
        expired: list[tuple[str, PendingMessage]] = []
        for nonce, msg in list(self.pending_messages.items()):
            if msg.is_expired():
                expired.append((nonce, msg))
                del self.pending_messages[nonce]
        return expired

    # ================================================================
    # Hop count validation
    # ================================================================

    def get_max_a2a_count(self) -> int | None:
        """返回 hop_count_map 中最大的 key（即当前最大的 a2a_count）。"""
        return max(self.hop_count_map) if self.hop_count_map else None

    def get_latest_intra_count(self, a2a_count: int) -> int | None:
        """返回指定 a2a_count 对应的最新 intra_count。"""
        return self.hop_count_map.get(a2a_count)

    # ================================================================
    # Trusted DID list
    # ================================================================

    def add_trusted_did(self, did: str) -> None:
        if did not in self.trusted_did_list:
            self.trusted_did_list.append(did)
        self.updated_at = time.time()

    def get_latest_trusted_did(self) -> str | None:
        return self.trusted_did_list[-1] if self.trusted_did_list else None

    def get_trusted_did_list(self) -> list[str]:
        return list(self.trusted_did_list)

    def clear_trusted_list(self) -> None:
        self.trusted_did_list.clear()

    # ================================================================
    # Nonce completion tracking
    # ================================================================

    def mark_nonce_completed(self, nonce: str) -> None:
        if nonce not in self.completed_nonces:
            self.completed_nonces.append(nonce)
        self.updated_at = time.time()

    def has_subsequent_activity_after(self, nonce: str) -> bool:
        """检查指定 nonce 之后是否还有其他 pending 或已完成的消息。"""
        for other_nonce, other_msg in self.pending_messages.items():
            if other_nonce == nonce:
                continue
            if not other_msg.is_expired():
                return True

        if self.completed_nonces and nonce not in self.completed_nonces:
            return True

        return False

    def has_subsequent_with_different_verified_identity(
        self, nonce: str, current_node_did: str,
    ) -> bool:
        """检查是否有其他 pending 消息通过了身份验证且身份与当前不同。"""
        for other_nonce, other_msg in self.pending_messages.items():
            if other_nonce == nonce:
                continue
            if other_msg.is_expired():
                continue
            if other_msg.identity_verified and other_msg.node_did != current_node_did:
                return True
        return False

    # ================================================================
    # Verification convenience
    # ================================================================

    def complete_verification(
        self, nonce: str, hop_count: list[int], trusted_did: str,
    ) -> None:
        """一次完成 Branch B 验证通过后的所有状态更新。"""
        self.remove_pending_message(nonce)
        self.hop_count_map[hop_count[0]] = hop_count[1]
        if trusted_did not in self.trusted_did_list:
            self.trusted_did_list.append(trusted_did)
        if nonce not in self.completed_nonces:
            self.completed_nonces.append(nonce)
        self.updated_at = time.time()

    # ================================================================
    # Generic metadata
    # ================================================================

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self.updated_at = time.time()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    # ================================================================
    # Analysis state
    # ================================================================

    def get_analysis_state(self) -> dict[str, Any]:
        return {
            "report_count": self.analysis.report_count,
            "last_trace_id": self.analysis.last_trace_id,
            "batch_index": self.analysis.batch_index,
            "context": self.analysis.context,
            "intent": self.analysis.intent,
        }

    def increment_report_count(self) -> int:
        self.analysis.report_count += 1
        self.updated_at = time.time()
        return self.analysis.report_count

    def reset_report_count(self) -> None:
        self.analysis.report_count = 0
        self.updated_at = time.time()

    def update_analysis_cursor(
        self, batch_index: int, last_trace_id: int, context: str,
    ) -> None:
        self.analysis.batch_index = batch_index
        self.analysis.last_trace_id = last_trace_id
        self.analysis.context = context
        self.updated_at = time.time()

    def set_intent(self, intent: dict) -> None:
        self.analysis.intent = intent
        self.updated_at = time.time()

    def get_intent(self) -> dict | None:
        return self.analysis.intent
