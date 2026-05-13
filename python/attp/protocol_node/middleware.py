"""消息拦截中间件 — Nonce 会话匹配 + 两阶段验证 + 行为记录。

实现 4 步串行验证管道：
1. 基础 Hop 验证（字段完整性、类型、值约束、超时）
2. 身份与签名验证（DID 解析 + hop 签名 + identity signature）
3. Nonce 会话分支（Branch A 暂存 / Branch B 匹配验证）
4. 行为类型推断 + hop_count 分规则校验
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attp.app.logging import get_logger
from attp.core.authentication.did_resolver import DIDResolver, VALID_NODE_TYPES
from attp.core.authentication.signatures import verify_signature
from attp.core.provenance.hashing import calculate_hop_hash
from attp.core.sessions.pending_message import PendingMessage

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


async def intercept_record(
    body: dict,
    did_resolver: DIDResolver,
    tracer,
    chain_manager,
    session_manager,
    agent_did: str,
) -> InterceptResult:
    """消息拦截核心逻辑 — 4 步验证管道。

    Args:
        body: 请求 JSON body。
        did_resolver: DID 解析器实例。
        tracer: MessageTracer 实例。
        chain_manager: ChainManager 实例（用于 validate_hop）。
        session_manager: SessionManager 实例（用于 nonce 暂存）。
        agent_did: 协议节点所属 agent 的 DID。

    Returns:
        InterceptResult 拦截结果。
    """
    metadata = body.get("metadata") or {}
    record_log = metadata.get("Record_Log") or {}
    session_id = metadata.get("Session_ID", "")
    pna = metadata.get("Protocol_Node_Address", "")

    # ==================== Step 1: 基础 Hop 验证 ====================
    if not record_log:
        return InterceptResult(
            status="error", node_type=None,
            error="missing_record_log", sender_did=None,
        )

    ok, hop_error = chain_manager.validate_hop(record_log)
    if not ok:
        return InterceptResult(
            status="error", node_type=None,
            error=f"hop_validation:{hop_error}", sender_did=None,
        )

    # ==================== Step 2: 身份与签名验证 ====================
    sender_did = record_log.get("node_did", "")

    # 2a. DID 解析 → 公钥 + 节点类型
    result = await did_resolver.resolve_full(sender_did)
    if result.public_key is None:
        logger.warning("DID resolution failed for sender: {}", sender_did)
        return InterceptResult(
            status="error", node_type=None,
            error="did_resolution_failed", sender_did=sender_did,
        )

    node_type = result.node_type
    if node_type is None:
        return InterceptResult(
            status="error", node_type=None,
            error="missing_type_field", sender_did=sender_did,
        )
    if node_type not in VALID_NODE_TYPES:
        return InterceptResult(
            status="error", node_type=node_type,
            error="invalid_type", sender_did=sender_did,
        )

    # 2b. 验证 Identity Signature
    nonce = body.get("nonce") or metadata.get("nonce")
    identity_sig = metadata.get("Identity_Signature")
    if not nonce:
        return InterceptResult(
            status="error", node_type=node_type,
            error="missing_nonce", sender_did=sender_did,
        )
    if not identity_sig:
        return InterceptResult(
            status="error", node_type=node_type,
            error="missing_identity_signature", sender_did=sender_did,
        )
    identity_payload = f"{nonce}:{sender_did}"
    if not verify_signature(identity_payload, identity_sig, result.public_key):
        return InterceptResult(
            status="error", node_type=node_type,
            error="identity_signature_invalid", sender_did=sender_did,
        )

    # ==================== Step 3: Nonce 会话分支 ====================
    session = session_manager.get_or_create(session_id)
    stored_msg = session.get_pending_message(nonce)

    if stored_msg is None:
        # ====== Branch A: 首次到达（上游发送者 Phase 2） ======
        if sender_did != agent_did:
            return InterceptResult(
                status="error", node_type=node_type,
                error="sender_mismatch_not_self", sender_did=sender_did,
            )

        pending = PendingMessage(
            hop=record_log,
            session_id=session_id,
            protocol_node_address=pna,
            sender_did=sender_did,
            sender_node_type=node_type,
            nonce=nonce,
            stored_at=time.time(),
        )
        record_log["session_id"] = session_id
        record_log["protocol_node_address"] = pna
        session.store_pending_message(nonce, pending)
        session_manager.save(session)

        return InterceptResult(
            status="stored", node_type=node_type,
            error=None, sender_did=sender_did,
        )

    else:
        # ====== Branch B: 下游响应到达（Phase 1） ======

        # 3a. 校验：stored_msg 的目标就是当前消息的发送者
        if stored_msg.hop.get("target_did") != sender_did:
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error="receiver_mismatch", sender_did=sender_did,
            )

        # 3b. 内容真实性验证
        ok, error_msg = tracer.verify_back_propagation(
            stored_hop=stored_msg.hop,
            prev_hop=record_log,
            session_id=session_id,
            protocol_node_address=pna,
        )
        if not ok:
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error=f"back_propagation:{error_msg}", sender_did=sender_did,
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
                error="invalid_type_combination", sender_did=sender_did,
            )

        # 3d. hop_count=0 时类型必须为 U2A（用户意图入口）
        current_hc = record_log.get("Hop_Count", 0)
        if current_hc == 0 and behavior_type != "U2A":
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error="hop_zero_must_be_u2a", sender_did=sender_did,
            )

        # 3e. Hop Count 校验（当前对 vs 前一对已完成消息）
        prev_completed_hc = session.get_metadata("LastCompletedHopCount")
        if prev_completed_hc is not None:
            if behavior_type == "A2A":
                if current_hc != prev_completed_hc + 1:
                    session.remove_pending_message(nonce)
                    session_manager.save(session)
                    return InterceptResult(
                        status="error", node_type=node_type,
                        error="hop_count_violation_a2a", sender_did=sender_did,
                    )
            else:
                if current_hc != prev_completed_hc:
                    session.remove_pending_message(nonce)
                    session_manager.save(session)
                    return InterceptResult(
                        status="error", node_type=node_type,
                        error="hop_count_violation_non_a2a", sender_did=sender_did,
                    )

        # 3e. 清理暂存 + 记录本对 hop_count 供下一对比较
        session.remove_pending_message(nonce)
        session.set_metadata("LastCompletedHopCount", current_hc)
        session_manager.save(session)

        return InterceptResult(
            status="verified",
            node_type=receiver_type,
            error=None,
            sender_did=sender_did,
            target_did=stored_msg.hop.get("target_did"),
            behavior_type=behavior_type,
            stored_msg=stored_msg,
        )
