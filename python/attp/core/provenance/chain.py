"""核心链逻辑：追加跳和验证。"""

import time

from attp.app.logging import get_logger
from attp.core.authentication import KeyStore
from attp.core.authentication import sign_hash, verify_signature
from attp.core.provenance import calculate_genesis_hash, calculate_hop_hash

logger = get_logger("Tracing")

_HOP_REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "node_did": str,
    "target_did": str,
    "Hop_Count": int,
    "Timestamp": (float, int),
    "Signature": str,
    "Content": str,
}


class ChainManager:
    """管理消息跳的追加和验证。"""

    def __init__(self, key_store: KeyStore):
        self._key_store = key_store

    def append_hop(self, metadata: dict, content: str, node_did: str,
                   target_did: str, private_key_path: str,
                   increment_hop: bool = True) -> dict:
        metadata = metadata.copy()
        session_id = metadata.get("Session_ID")
        hop = metadata.get("Hop")
        if hop:
            hop_count = hop["Hop_Count"] + 1 if increment_hop else hop["Hop_Count"]
        else:
            hop_count = 0

        timestamp = time.time()
        hop_hash = calculate_hop_hash(
            content=content,
            sender_did=node_did,
            target_did=target_did,
            hop_count=hop_count,
            timestamp=timestamp,
            session_id=session_id,
        )

        private_key = self._key_store.load_private_key(private_key_path)
        signature = sign_hash(hop_hash, private_key)

        new_log_entry = {
            "node_did": node_did,
            "target_did": target_did,
            "Hop_Count": hop_count,
            "Timestamp": timestamp,
            "Signature": signature,
            "Content": content,
        }

        metadata["Hop"] = new_log_entry
        logger.debug("append_hop called with metadata={}", metadata)
        return metadata

    def validate_hop(
        self,
        hop: dict,
        timeout: float = 300.0,
    ) -> tuple[bool, str]:
        """校验单条 hop 的字段完整性、类型、值约束及超时。

        注意：hop_count 递增校验已移至 middleware 的 Branch B 中基于行为类型执行。

        Args:
            hop: 待校验的 hop 字典。
            timeout: 超时阈值（秒），0 则跳过超时校验。
        """
        # Step 1: 字段完整性 & 类型
        for field, expected_type in _HOP_REQUIRED_FIELDS.items():
            if field not in hop:
                return False, f"[FIELD_MISSING] Missing required field: {field}"
            if not isinstance(hop[field], expected_type):
                actual = type(hop[field]).__name__
                return False, f"[FIELD_TYPE] '{field}' expected {expected_type}, got {actual}"

        # Step 1b: 值约束
        if not hop["node_did"]:
            return False, "[FIELD_VALUE] 'node_did' must be non-empty"
        if not hop["target_did"]:
            return False, "[FIELD_VALUE] 'target_did' must be non-empty"
        if hop["Hop_Count"] < 0:
            return False, f"[HOP_COUNT] Hop_Count must be >= 0, got {hop['Hop_Count']}"
        if not hop["Signature"]:
            return False, "[FIELD_VALUE] 'Signature' must be non-empty"

        now = time.time()
        if hop["Timestamp"] <= 0:
            return False, f"[FIELD_VALUE] 'Timestamp' must be positive, got {hop['Timestamp']}"
        if hop["Timestamp"] > now:
            return False, f"[FIELD_VALUE] 'Timestamp' is in the future ({hop['Timestamp']} > now {now})"

        # Step 2: timestamp 超时
        if timeout > 0:
            elapsed = now - hop["Timestamp"]
            if elapsed > timeout:
                return False, (f"[TIMESTAMP_EXPIRED] Hop timestamp {hop['Timestamp']} "
                               f"exceeded timeout {timeout}s (elapsed: {elapsed:.1f}s)")

        return True, ""

    def verify_back_propagation(
        self,
        stored_hop: dict,
        prev_hop: dict,
        session_id: str,
    ) -> tuple[bool, str]:
        """验证回传 record 与已存储 record 的一致性。

        对比 Branch A 暂存的 hop 与 Branch B 到达的 hop，检测篡改。

        Args:
            stored_hop: Branch A 暂存的 hop dict。
            prev_hop: Branch B 到达的 hop dict（从 BackMessage.recorded_hop 构造）。
            session_id: 会话标识。
        Returns:
            (True, "") 验证通过；(False, 错误描述) 验证失败。
        """
        if not prev_hop:
            return True, ""

        if not stored_hop:
            logger.warning("Back-prop: prev_hop present but no stored record")
            return False, "No stored record to verify against"

        prev_sign = prev_hop.get("Signature", "")
        prev_node_did = prev_hop.get("node_did", "")

        store_hop_hash = calculate_hop_hash(
            content=stored_hop.get("Content", ""),
            sender_did=stored_hop.get("node_did", ""),
            target_did=stored_hop.get("target_did", ""),
            hop_count=stored_hop.get("Hop_Count", 0),
            timestamp=stored_hop.get("Timestamp", 0.0),
            session_id=stored_hop.get("session_id"),
        )

        prev_hop_hash = calculate_hop_hash(
            content=prev_hop.get("Content", ""),
            sender_did=prev_node_did,
            target_did=prev_hop.get("target_did", ""),
            hop_count=prev_hop.get("Hop_Count", 0),
            timestamp=prev_hop.get("Timestamp", 0.0),
            session_id=session_id,
        )

        prev_public_key = self._key_store.get(prev_node_did)
        if prev_public_key is None:
            logger.error("Back-prop: No public key for previous node {}", prev_node_did)
            return False, f"No public key for previous node {prev_node_did}"

        step1_ok = verify_signature(prev_hop_hash, prev_sign, prev_public_key)
        step2_ok = stored_hop.get("Signature") == prev_sign
        step3_ok = store_hop_hash == prev_hop_hash

        if step1_ok and step2_ok and step3_ok:
            return True, ""

        if not step1_ok and not step2_ok:
            error = "节点篡改内容 (Current node tampered with content)"
        elif not step1_ok and step2_ok and not step3_ok:
            error = "节点篡改pre_content (Current node tampered with pre_content)"
        elif not step1_ok and step2_ok and step3_ok:
            error = "上一节点栽赃下一节点 (Previous node framed the next node)"
        elif step1_ok and step2_ok and not step3_ok:
            error = "上一节点签名和内容不匹配 (Previous node signature/content mismatch)"
        else:
            error = "未知验证失败 (Unknown verification failure)"

        logger.error("Back-prop verification FAILED: session={}, error={}", session_id, error)
        return False, error

