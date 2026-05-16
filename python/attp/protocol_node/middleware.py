"""消息拦截中间件 — Nonce 会话匹配 + 两阶段验证 + 行为记录。

实现 4 步串行验证管道：
1. 基础字段验证（BackMessage 结构完整性）
2. 身份与签名验证（DID 解析 + identity signature + content signature）
3. Nonce 会话分支（Branch A 暂存 / Branch B 匹配验证）
4. 行为类型推断 + hop_count 分规则校验
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attp.app.logging import get_logger
from attp.core.authentication.did_resolver import DIDResolver, VALID_NODE_TYPES
from attp.core.message.event import BackMessage
from attp.core.sessions.protocol_node import PendingMessage

logger = get_logger("Middleware")

# 5 种合法的行为类型映射：(sender_node_type, receiver_node_type) → field_type
BEHAVIOR_TYPE_MAP: dict[tuple[str, str], str] = {
    ("agent", "tool"): "A2T",
    ("agent", "user"): "A2U",
    ("user", "agent"): "U2A",
    ("agent", "agent"): "A2A",
    ("tool", "agent"): "T2A",
}


@dataclass
class InterceptResult:
    """拦截结果。"""

    status: str             # "stored" / "verified" / "error"
    node_type: str | None
    error: str | None
    sender_did: str | None
    target_did: str | None = None
    behavior_type: str | None = None
    stored_msg: Any = None  # Branch B 时携带的 PendingMessage


def _validate_back_message(back_msg: BackMessage) -> tuple[bool, str]:
    """校验 BackMessage 基础字段完整性。"""
    if not back_msg.node_did:
        return False, "node_did is empty"
    if not back_msg.nonce:
        return False, "nonce is empty"
    if not back_msg.sig_identity:
        return False, "sig_identity is empty"

    r = back_msg.recorded_hop
    if not r.session_id:
        return False, "session_id is empty"
    if not r.sender_did:
        return False, "sender_did is empty"
    if not r.target_did:
        return False, "target_did is empty"
    if r.hop_count < 0:
        return False, f"hop_count must be >= 0, got {r.hop_count}"
    if r.timestamp <= 0:
        return False, f"timestamp must be positive, got {r.timestamp}"
    if not r.sig_content:
        return False, "sig_content is empty"

    return True, ""


async def intercept_record(
    back_msg: BackMessage,
    did_resolver: DIDResolver,
    tracer,
    session_manager,
) -> InterceptResult:
    """消息拦截核心逻辑 — 4 步验证管道。

    Args:
        back_msg: 解析后的 BackMessage 对象。
        did_resolver: DID 解析器实例。
        tracer: ProtocolTracer 实例。
        chain_manager: ChainManager 实例（用于 validate_hop）。
        session_manager: SessionManager 实例（用于 nonce 暂存）。

    Returns:
        InterceptResult 拦截结果。
    """
    node_did = back_msg.node_did
    nonce = back_msg.nonce
    recorded = back_msg.recorded_hop
    session_id = recorded.session_id
    pna = back_msg.protocol_url

    # ==================== Step 1: 基础字段验证 ====================
    ok, field_error = _validate_back_message(back_msg)
    if not ok:
        return InterceptResult(
            status="error", node_type=None,
            error=f"hop_validation:{field_error}", sender_did=None,
        )

    # ==================== Step 2: 身份与签名验证 ====================
    # 2a. DID 解析 → 公钥 + 节点类型
    result = await did_resolver.resolve_full(node_did)
    if result.public_key is None:
        logger.warning("DID resolution failed for sender: {}", node_did)
        return InterceptResult(
            status="error", node_type=None,
            error="did_resolution_failed", sender_did=node_did,
        )

    node_type = result.node_type
    if node_type is None:
        return InterceptResult(
            status="error", node_type=None,
            error="missing_type_field", sender_did=node_did,
        )
    if node_type not in VALID_NODE_TYPES:
        return InterceptResult(
            status="error", node_type=node_type,
            error="invalid_type", sender_did=node_did,
        )

    # 2b. 验证 Identity Signature
    if not back_msg.verify_identity(result.public_key):
        return InterceptResult(
            status="error", node_type=node_type,
            error="identity_signature_invalid", sender_did=node_did,
        )

    # 2c. 验证 Content Signature（发送方签名）
    # 需要用 recorded_hop.sender_did 的公钥验签
    sender_result = await did_resolver.resolve_full(recorded.sender_did)
    if sender_result.public_key is None:
        return InterceptResult(
            status="error", node_type=node_type,
            error="did_resolution_failed", sender_did=recorded.sender_did,
        )
    if not back_msg.verify_content(sender_result.public_key):
        return InterceptResult(
            status="error", node_type=node_type,
            error="content_signature_invalid", sender_did=node_did,
        )

    # ==================== Step 3: Nonce 会话分支 ====================
    session = session_manager.get_or_create(session_id)
    stored_msg = session.get_pending_message(nonce)

    # 构造 PendingMessage 用的 hop dict（保持 PendingMessage 接口不变）
    hop_dict = {
        "node_did": recorded.sender_did,
        "target_did": recorded.target_did,
        "Content": recorded.content,
        "Timestamp": recorded.timestamp,
        "Hop_Count": recorded.hop_count,
        "Signature": recorded.sig_content,
    }

    if stored_msg is None:
        # ====== Branch A: 首次到达（上游发送者 Phase 2） ======

        pending = PendingMessage(
            hop=hop_dict,
            session_id=session_id,
            protocol_node_address=pna,
            sender_did=recorded.sender_did,
            sender_node_type=node_type,
            nonce=nonce,
            stored_at=time.time(),
        )
        hop_dict["session_id"] = session_id
        hop_dict["protocol_node_address"] = pna
        session.store_pending_message(nonce, pending)
        session_manager.save(session)

        return InterceptResult(
            status="stored", node_type=node_type,
            error=None, sender_did=recorded.sender_did,
        )

    else:
        # ====== Branch B: 下游响应到达（Phase 1） ======

        # 3a. 校验：stored_msg 的目标就是当前消息的发送者
        if stored_msg.hop.get("target_did") != node_did:
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error="receiver_mismatch", sender_did=node_did,
            )

        # 3b. 内容一致性验证（stored hop 与当前 recorded_hop）
        ok, error_msg = tracer.verify_back_propagation(
            stored_hop=stored_msg.hop,
            prev_hop=hop_dict,
            session_id=session_id,
            protocol_node_address=pna,
        )
        if not ok:
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error=f"back_propagation:{error_msg}", sender_did=node_did,
            )

        # 3c. 推断行为类型
        sender_type = stored_msg.sender_node_type
        receiver_type = node_type
        behavior_type = BEHAVIOR_TYPE_MAP.get((sender_type, receiver_type))
        if behavior_type is None:
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error="invalid_type_combination", sender_did=node_did,
            )

        # 3d. hop_count=0 时类型必须为 U2A（用户意图入口）
        current_hc = recorded.hop_count
        if current_hc == 0 and behavior_type != "U2A":
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error="hop_zero_must_be_u2a", sender_did=node_did,
            )

        # 3e. Hop Count 校验（当前对 vs 前一对已完成消息）
        prev_completed_hc = session.get_last_completed_hop_count()
        if prev_completed_hc is not None:
            if behavior_type == "A2A":
                if current_hc != prev_completed_hc + 1:
                    session.remove_pending_message(nonce)
                    session_manager.save(session)
                    return InterceptResult(
                        status="error", node_type=node_type,
                        error="hop_count_violation_a2a", sender_did=node_did,
                    )
            else:
                if current_hc != prev_completed_hc:
                    session.remove_pending_message(nonce)
                    session_manager.save(session)
                    return InterceptResult(
                        status="error", node_type=node_type,
                        error="hop_count_violation_non_a2a", sender_did=node_did,
                    )

        # 清理暂存 + 记录本对 hop_count 供下一对比较
        session.remove_pending_message(nonce)
        session.set_last_completed_hop_count(current_hc)
        session_manager.save(session)

        return InterceptResult(
            status="verified",
            node_type=receiver_type,
            error=None,
            sender_did=node_did,
            target_did=stored_msg.hop.get("target_did"),
            behavior_type=behavior_type,
            stored_msg=stored_msg,
        )
