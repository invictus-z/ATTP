"""消息拦截中间件 — 可信名单校验 + 恶意节点判定 + 行为记录。

实现验证管道：
1. 基础字段验证（BackMessage 结构完整性）
2. 身份签名验证（DID 解析 + identity signature）
3. 可信名单校验（新增：回传1身份必须在可信名单中）
4. Nonce 会话分支：
   - Branch A（回传1）：身份验证 + 可信名单校验 → 暂存
   - Branch B（回传2）：恶意节点判定引擎 → verify_back_propagation → 行为推断
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from attp.app.logging import get_logger
from attp.core.authentication.did_resolver import DIDResolver, VALID_NODE_TYPES
from attp.core.message.event import BackMessage
from attp.protocol_node.malicious_detector import (
    EvidenceType,
    MaliciousNodeDetector,
    MaliciousNodeReport,
)
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

    status: str             # "stored" / "verified" / "error" / "malicious"
    node_type: str | None
    error: str | None
    sender_did: str | None
    target_did: str | None = None
    behavior_type: str | None = None
    stored_msg: Any = None  # Branch B 时携带的 PendingMessage
    malicious_report: MaliciousNodeReport | None = None  # 恶意检测报告


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
    malicious_detector: MaliciousNodeDetector,
) -> InterceptResult:
    """消息拦截核心逻辑 — 验证管道。

    Args:
        back_msg: 解析后的 BackMessage 对象。
        did_resolver: DID 解析器实例。
        tracer: ProtocolTracer 实例。
        session_manager: SessionManager 实例（用于 nonce 暂存）。
        malicious_detector: MaliciousNodeDetector 实例。

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

    # ==================== Step 2: 身份签名验证 ====================
    # 2. DID 解析 → 公钥 + 节点类型
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

    # ==================== Step 3: Nonce 会话分支 ====================
    session = session_manager.get_or_create(session_id)
    stored_msg = session.get_pending_message(nonce)

    # 构造 PendingMessage 用的 hop dict
    hop_dict = {
        "node_did": recorded.sender_did,
        "target_did": recorded.target_did,
        "Content": recorded.content,
        "Timestamp": recorded.timestamp,
        "Hop_Count": recorded.hop_count,
        "Signature": recorded.sig_content,
        "session_id": session_id,
        "protocol_node_address": pna,
    }

    if stored_msg is None:
        # ====== Branch A: 回传1 到达 ======
        # 3. 验证 Identity Signature 以及 可信名单是否匹配
        trusted_did = session.get_trusted_target_did()

        # 回传1 身份签名无法解开
        identity_ok = back_msg.verify_identity(result.public_key)
        if not identity_ok:
            malicious = trusted_did if trusted_did else node_did
            if malicious_detector:
                report = MaliciousNodeReport(
                    malicious_dids=[malicious],
                    evidence_type=EvidenceType.IDENTITY_TAMPERING,
                    evidence_description=(
                        f"回传1的身份签名无法用DID解析出的公钥验证，"
                        f"恶意节点: {malicious}"
                    ),
                    session_id=session_id,
                    nonce=nonce,
                    timestamp=time.time(),
                    raw_evidence={"node_did": node_did, "trusted_did": trusted_did},
                )
                await tracer.save_malicious_report(report)
                return InterceptResult(
                    status="malicious", node_type=node_type,
                    error="identity_signature_invalid", sender_did=node_did,
                    malicious_report=report,
                )
            return InterceptResult(
                status="error", node_type=node_type,
                error="identity_signature_invalid", sender_did=node_did,
            )
        
        if trusted_did is not None and node_did != trusted_did:
            # 回传1 的身份与可信名单不一致 → 可信名单中的节点为恶意
            if malicious_detector:
                report = MaliciousNodeReport(
                    malicious_dids=[trusted_did],
                    evidence_type=EvidenceType.TRUSTED_LIST_VIOLATION,
                    evidence_description=(
                        f"回传1的DID({node_did})与可信名单({trusted_did})不一致，"
                        f"可信名单中的节点为恶意"
                    ),
                    session_id=session_id,
                    nonce=nonce,
                    timestamp=time.time(),
                    raw_evidence={"node_did": node_did, "trusted_did": trusted_did},
                )
                await tracer.save_malicious_report(report)
                return InterceptResult(
                    status="malicious", node_type=node_type,
                    error="trusted_list_violation", sender_did=node_did,
                    malicious_report=report,
                )
            return InterceptResult(
                status="error", node_type=node_type,
                error="trusted_list_violation", sender_did=node_did,
            )

        # 暂存，等待下一步验证或判断
        pending = PendingMessage(
            hop=hop_dict,
            session_id=session_id,
            protocol_node_address=pna,
            sender_did=recorded.sender_did,
            sender_node_type=node_type,
            nonce=nonce,
            stored_at=time.time(),
            node_did=node_did,
            identity_public_key_pem=None,
            identity_verified=identity_ok,
        )
        session.store_pending_message(nonce, pending)
        session_manager.save(session)

        return InterceptResult(
            status="stored", node_type=node_type,
            error=None, sender_did=recorded.sender_did,
        )

    else:
        # ====== Branch B: 回传2 到达（接收方回传） ======

        # 3. 回传2 身份签名验证（兜底：恶意检测器内部也会验证，此处为无检测器时的保底）
        if not malicious_detector:
            if not back_msg.verify_identity(result.public_key):
                return InterceptResult(
                    status="error", node_type=node_type,
                    error="identity_signature_invalid", sender_did=node_did,
                )

        # Step 4: 恶意节点判定引擎
        if malicious_detector:
            report = await malicious_detector.evaluate_dual_back_prop(
                stored_msg=stored_msg,
                back_msg_2=back_msg,
            )
            if report:
                # 恶意节点检测到
                session.remove_pending_message(nonce)
                session_manager.save(session)
                await tracer.save_malicious_report(report)
                return InterceptResult(
                    status="malicious", node_type=node_type,
                    error="malicious_node_detected", sender_did=node_did,
                    malicious_report=report,
                )

        # Step 5: 内容一致性验证（复用现有 verify_back_propagation）
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

        # Step 6: 推断行为类型
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

        # 6a. hop_count=0 时类型必须为 U2A
        current_hc = recorded.hop_count
        if current_hc == 0 and behavior_type != "U2A":
            session.remove_pending_message(nonce)
            session_manager.save(session)
            return InterceptResult(
                status="error", node_type=node_type,
                error="hop_zero_must_be_u2a", sender_did=node_did,
            )

        # 6b. Hop Count 校验
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

        # Step 7: 验证通过，更新可信名单
        session.remove_pending_message(nonce)
        session.set_last_completed_hop_count(current_hc)
        session.set_trusted_target_did(recorded.target_did)
        session.mark_nonce_completed(nonce)
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
