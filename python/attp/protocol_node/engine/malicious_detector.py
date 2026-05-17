"""恶意节点判定引擎 — 双回传/单回传场景的恶意节点决策树。

实现方案中的恶意节点判定机制：
- 双回传：回传1身份验证 → 回传2身份验证 → DID 比对 → 内容签名交叉验证
- 单回传：身份检查 → 可信名单比对 → 后续活动检测
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
        session,
    ) -> MaliciousNodeReport | None:
        """双回传场景恶意判定。

        完整决策树：回传1身份验证 → 可信名单校验 → 回传2身份验证
        → DID 比对 → 内容签名交叉验证。

        Args:
            stored_msg: 回传1（先到达，已暂存，身份验证结果在 identity_verified 中）
            back_msg_2: 回传2（后到达，当前消息）
            session: ProtocolSession 实例（用于可信名单访问）

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

        trusted_list = session.get_trusted_did_list()

        # --- Step 0a: 回传1身份签名检查 ---
        if not stored_msg.identity_verified:
            # 恶意节点必然在可信名单中，一起通报
            if trusted_list:
                return _build_report(
                    malicious_dids=list(trusted_list),
                    evidence_type=EvidenceType.IDENTITY_TAMPERING,
                    description=f"回传1身份签名无法验证，"
                                f"恶意节点在可信名单中，一起通报: {trusted_list}",
                    session_id=session_id,
                    nonce=nonce,
                    raw_evidence=raw_evidence,
                )
            # 可信名单为空（Session 初始状态），报告回传1的 node_did
            return _build_report(
                malicious_dids=[bp1_did],
                evidence_type=EvidenceType.IDENTITY_TAMPERING,
                description=f"回传1身份签名无法验证(无可信名单)，"
                            f"报告发送者: {bp1_did}",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Step 0b: 回传1可信名单校验 ---
        latest_trusted = session.get_latest_trusted_did()
        if latest_trusted is not None and bp1_did != latest_trusted:
            # 回传1 DID 与最新名单不一致 → 可信名单中的节点为恶意
            return _build_report(
                malicious_dids=list(trusted_list),
                evidence_type=EvidenceType.TRUSTED_LIST_VIOLATION,
                description=f"回传1的DID({bp1_did})与最新名单({latest_trusted})不一致，"
                            f"可信名单中的节点为恶意，一起通报: {trusted_list}",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Step 1: 回传2身份签名检查 ---
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

        # --- Step 3: 回传1内容签名自检 ---
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

        # --- Step 4: 回传2内容签名交叉验证 ---
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
        # 无法区分是发送方伪造还是接收方篡改，两节点一起通报
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
        """单回传场景恶意判定 — 完整决策树。

        恶意节点行为可能性：
        1. 接收了没回传（后续必定还会作恶，可通过 Payload 暴露）
        2. 没发送却发送了回传（纯垃圾消息）
        3. 发送了没回传（虽找不到恶意发送节点，但接收方依然会回传真实内容）
        4. 发送了但 nonce 不一样，导致两条单回传

        Args:
            pending_msg: 唯一的回传消息（身份验证结果在 identity_verified 中）
            session: ProtocolSession 实例

        Returns:
            MaliciousNodeReport 如果检测到恶意，None 如果应抛弃。
        """
        session_id = pending_msg.session_id
        nonce = pending_msg.nonce
        node_did = pending_msg.node_did

        raw_evidence = {
            "pending_msg": pending_msg.to_dict(),
        }

        trusted_list = session.get_trusted_did_list()

        # --- Case A: 身份签名解不开 ---
        if not pending_msg.identity_verified:
            if trusted_list:
                return _build_report(
                    malicious_dids=list(trusted_list),
                    evidence_type=EvidenceType.IDENTITY_TAMPERING,
                    description=f"单回传身份签名无效，对应情况2(垃圾消息)，"
                                f"可信名单中的节点为恶意，一起通报: {trusted_list}",
                    session_id=session_id,
                    nonce=nonce,
                    raw_evidence=raw_evidence,
                )
            return _build_report(
                malicious_dids=[node_did],
                evidence_type=EvidenceType.IDENTITY_TAMPERING,
                description=f"单回传身份签名无效(无可信名单)，报告发送者: {node_did}",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Case B: 身份签名解得开，但 DID ≠ 最新名单 ---
        latest_trusted = session.get_latest_trusted_did()
        if latest_trusted is not None and node_did != latest_trusted:
            return _build_report(
                malicious_dids=list(trusted_list),
                evidence_type=EvidenceType.TRUSTED_LIST_VIOLATION,
                description=f"单回传DID({node_did})与最新名单({latest_trusted})不一致，"
                            f"可信名单中的节点为恶意，一起通报: {trusted_list}",
                session_id=session_id,
                nonce=nonce,
                raw_evidence=raw_evidence,
            )

        # --- Case C: 身份签名解得开，且 DID = 最新名单 ---
        has_subsequent = session.has_subsequent_activity_after(nonce)

        if has_subsequent:
            # 检查是否有后续消息能验证身份且身份不一致
            has_diff = session.has_subsequent_with_different_verified_identity(
                nonce, node_did,
            )
            if has_diff:
                # 判定为"接收了但未回传"，target_did 为恶意
                target = pending_msg.hop.get("target_did", "")
                return _build_report(
                    malicious_dids=[target],
                    evidence_type=EvidenceType.NO_PROPAGATION,
                    description=f"单回传+后续有不同身份消息："
                                f"节点接收了但未回传，target({target})为恶意",
                    session_id=session_id,
                    nonce=nonce,
                    raw_evidence=raw_evidence,
                )
            # 后续消息都是恶意节点发的，不予记录
            logger.info(
                "单回传有后续活动但无不同身份，视为恶意节点自发自弃: "
                "session={}, nonce={}", session_id, nonce,
            )
            return None

        # 无后续消息 → 抛弃，不予记录
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
