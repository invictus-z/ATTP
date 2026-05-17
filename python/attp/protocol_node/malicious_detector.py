"""恶意节点判定引擎 — 双回传/单回传场景的恶意节点决策树。

实现方案中的恶意节点判定机制：
- 双回传：身份签名 → DID 比对 → 内容签名交叉验证
- 单回传：可信名单比对 + 后续活动检测
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from attp.app.logging import get_logger
from attp.core.authentication.did_resolver import DIDResolver
from attp.core.message.event import BackMessage
from attp.core.sessions.protocol_node import PendingMessage

logger = get_logger("MaliciousDetector")


class EvidenceType(Enum):
    IDENTITY_TAMPERING = "identity_tampering"
    TRUSTED_LIST_VIOLATION = "trusted_list_violation"
    CONTENT_TAMPERING = "content_tampering"
    NO_PROPAGATION = "no_propagation"
    FRAMING = "framing"
    INDISTINGUISHABLE_PAIR = "indistinguishable_pair"
    SAME_DID_DUPLICATE = "same_did_duplicate"


@dataclass
class MaliciousNodeReport:
    malicious_dids: list[str]
    evidence_type: EvidenceType
    evidence_description: str
    session_id: str
    nonce: str
    timestamp: float
    raw_evidence: dict


def _build_report(
    malicious_dids: list[str],
    evidence_type: EvidenceType,
    description: str,
    session_id: str,
    nonce: str,
    raw_evidence: dict,
) -> MaliciousNodeReport:
    return MaliciousNodeReport(
        malicious_dids=malicious_dids,
        evidence_type=evidence_type,
        evidence_description=description,
        session_id=session_id,
        nonce=nonce,
        timestamp=time.time(),
        raw_evidence=raw_evidence,
    )


class MaliciousNodeDetector:
    """恶意节点判定引擎。

    所有判定方法均为 async，因为需要通过 DIDResolver 解析公钥。
    """

    def __init__(self, did_resolver: DIDResolver):
        self._did_resolver = did_resolver

    async def evaluate_dual_back_prop(
        self,
        stored_msg: PendingMessage,
        back_msg_2: BackMessage,
    ) -> MaliciousNodeReport | None:
        """双回传场景恶意判定。

        回传1 的身份签名验证和可信名单校验已在 middleware Branch A 中完成，
        此处仅负责回传2 的检查、DID 比对和内容签名交叉验证。

        Args:
            stored_msg: 回传1（先到达，已暂存，身份+名单校验已通过）
            back_msg_2: 回传2（后到达，当前消息）

        Returns:
            MaliciousNodeReport 如果检测到恶意，None 如果通过。
        """
        session_id = stored_msg.session_id
        nonce = stored_msg.nonce
        bp1_did = stored_msg.node_did

        raw_evidence = {
            "stored_msg": stored_msg.to_dict(),
            "back_msg_2": back_msg_2.to_dict(),
        }

        # --- Step 1: 回传2 身份签名检查 ---
        bp2_did = back_msg_2.node_did
        bp2_result = await self._did_resolver.resolve_full(bp2_did)
        if bp2_result.public_key is None:
            # 回传2 DID 解析失败，提取回传1的 target_did 为恶意节点
            target = stored_msg.hop.get("target_did", bp2_did)
            return _build_report(
                malicious_dids=[target],
                evidence_type=EvidenceType.IDENTITY_TAMPERING,
                description=f"回传2身份签名无效(DID解析失败)，"
                            f"判定回传1的target({target})为恶意节点",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        if not back_msg_2.verify_identity(bp2_result.public_key):
            target = stored_msg.hop.get("target_did", bp2_did)
            return _build_report(
                malicious_dids=[target],
                evidence_type=EvidenceType.IDENTITY_TAMPERING,
                description=f"回传2身份签名验证失败，"
                            f"判定回传1的target({target})为恶意节点",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Step 2: DID 比对 ---
        if bp1_did == bp2_did:
            return _build_report(
                malicious_dids=[bp1_did],
                evidence_type=EvidenceType.SAME_DID_DUPLICATE,
                description=f"两条回传DID相同({bp1_did})，该节点为恶意",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Step 3: 回传1 内容签名自检 ---
        bp1_sender_did = stored_msg.sender_did
        bp1_sender_result = await self._did_resolver.resolve_full(bp1_sender_did)
        if bp1_sender_result.public_key is None:
            return _build_report(
                malicious_dids=[bp1_did],
                evidence_type=EvidenceType.CONTENT_TAMPERING,
                description=f"回传1发送者DID({bp1_sender_did})解析失败，"
                            f"回传1({bp1_did})为恶意",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # 构造回传1的 BackMessage 用于验证内容签名
        bp1_sig_content = stored_msg.hop.get("Signature", "")
        bp1_content_hash = self._compute_recorded_hop_content_hash(stored_msg.hop)

        if not self._verify_content_sig(
            bp1_content_hash, bp1_sig_content, bp1_sender_result.public_key,
        ):
            return _build_report(
                malicious_dids=[bp1_did],
                evidence_type=EvidenceType.CONTENT_TAMPERING,
                description=f"回传1的DID({bp1_did})不能解开自身内容签名，发送者为恶意",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Step 4: 回传2 内容签名交叉验证 ---
        bp2_content_hash = back_msg_2.recorded_hop.content_hash()

        # 尝试用回传1发送者的公钥验证回传2的内容签名
        if self._verify_content_sig(
            bp2_content_hash,
            back_msg_2.recorded_hop.sig_content,
            bp1_sender_result.public_key,
        ):
            # 身份确认通过，无恶意，交给后续 verify_back_propagation
            return None

        # 回传1发送者的公钥不能解开回传2的内容签名
        # 无法区分是发送方伪造了内容签名还是接收方篡改了内容签名
        return _build_report(
            malicious_dids=[bp1_did, bp2_did],
            evidence_type=EvidenceType.INDISTINGUISHABLE_PAIR,
            description=f"无法区分恶意方：回传1发送者({bp1_sender_did})公钥"
                        f"无法验证回传2({bp2_did})的内容签名，两节点一起通报",
            session_id=session_id,
            nonce=nonce,
            raw_evidence=raw_evidence,
        )

    async def evaluate_single_back_prop(
        self,
        pending_msg: PendingMessage,
        session,
    ) -> MaliciousNodeReport | None:
        """单回传场景恶意判定。

        回传1 的身份签名验证和可信名单校验已在 middleware Branch A 中完成，
        此处仅负责后续活动检测以区分「接收未回传」与「未发送却回传」。

        Args:
            pending_msg: 唯一的回传消息（已过期或 session 结束时残留，身份+名单已通过）
            session: ProtocolSession 实例（用于检测后续活动）

        Returns:
            MaliciousNodeReport 如果检测到恶意，None 如果应抛弃。
        """
        session_id = pending_msg.session_id
        nonce = pending_msg.nonce

        raw_evidence = {
            "pending_msg": pending_msg.to_dict(),
        }

        # 检查 session 是否有后续活动
        has_subsequent = session.has_subsequent_activity_after(nonce)

        if has_subsequent:
            # 判定为"接收了但未回传"，当前 payload 的 target_did 为恶意
            target = pending_msg.hop.get("target_did", "")
            return _build_report(
                malicious_dids=[target],
                evidence_type=EvidenceType.NO_PROPAGATION,
                description=f"单回传+后续活动存在：节点接收了但未回传，"
                            f"target({target})为恶意",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # 无后续消息 → 判定为"未发送却发了回传"（垃圾消息），抛弃
        logger.info(
            "单回传无后续活动，视为垃圾消息抛弃: session={}, nonce={}",
            session_id, nonce,
        )
        return None

    # -- internal helpers --

    @staticmethod
    def _compute_recorded_hop_content_hash(hop: dict) -> str:
        """从 hop dict 计算内容哈希（与 RecordedHop.content_hash 逻辑一致）。"""
        import hashlib
        import json
        raw = json.dumps({
            "session_id": hop.get("session_id", ""),
            "sender_did": hop.get("node_did", ""),
            "target_did": hop.get("target_did", ""),
            "content": hop.get("Content", ""),
            "timestamp": hop.get("Timestamp", 0.0),
            "hop_count": hop.get("Hop_Count", 0),
        }, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _verify_content_sig(
        content_hash: str, sig_content: str, public_key,
    ) -> bool:
        """验证内容签名。"""
        from attp.core.authentication.signatures import verify_signature
        if not sig_content:
            return False
        return verify_signature(content_hash, sig_content, public_key)
