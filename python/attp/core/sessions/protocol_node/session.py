"""ProtocolSession — 协议节点层 per-session 验证状态 + 分析状态容器。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .pending_message import PendingMessage


@dataclass
class VerticalAnalysisState:
    """纵向分析状态 — 意图流 / 隐状态 / 打分游标（逐跳改版）。

    字段语义：
        initiator_did        — 会话发起者 DID（首条 [0,0] U2A 的发送方），意图只采信它的 U2A
        intent_revisions     — 意图流 I=[Δ_0..Δ_m]，每条核验过的发起者 U2A 追加一个 Δ（dict）
        hidden_state         — 定长滚动隐状态 h_i（复用 context_summary）
        last_scored_trace_id — 已打分的最大 trace_id（纵轴游标，崩溃恢复用）
    """

    initiator_did: str = ""
    intent_revisions: list[dict] = field(default_factory=list)
    hidden_state: str = ""
    last_scored_trace_id: int = 0


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

    # -- 纵向分析状态 --
    vertical_analysis: VerticalAnalysisState = field(default_factory=VerticalAnalysisState)

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
    # Analysis state（逐跳改版：意图流 / 隐状态 / 打分游标）
    # ================================================================

    def get_analysis_state(self) -> dict[str, Any]:
        return {
            "initiator_did": self.vertical_analysis.initiator_did,
            "intent_revisions": list(self.vertical_analysis.intent_revisions),
            "hidden_state": self.vertical_analysis.hidden_state,
            "last_scored_trace_id": self.vertical_analysis.last_scored_trace_id,
        }

    def set_initiator_did(self, did: str) -> None:
        if not self.vertical_analysis.initiator_did and did:
            self.vertical_analysis.initiator_did = did
            self.updated_at = time.time()

    def get_initiator_did(self) -> str:
        return self.vertical_analysis.initiator_did

    def append_intent_revision(self, revision: dict) -> None:
        """追加一条意图增量 Δ_i 到意图流（只增不改）。"""
        self.vertical_analysis.intent_revisions.append(revision)
        self.updated_at = time.time()

    def get_intent_revisions(self) -> list[dict]:
        return list(self.vertical_analysis.intent_revisions)

    def set_hidden_state(self, hidden: str) -> None:
        self.vertical_analysis.hidden_state = hidden
        self.updated_at = time.time()

    def get_hidden_state(self) -> str:
        return self.vertical_analysis.hidden_state

    def advance_score_cursor(self, trace_id: int) -> None:
        """推进打分游标到 max(已记录, trace_id)。"""
        if trace_id > self.vertical_analysis.last_scored_trace_id:
            self.vertical_analysis.last_scored_trace_id = trace_id
            self.updated_at = time.time()

    def get_score_cursor(self) -> int:
        return self.vertical_analysis.last_scored_trace_id
