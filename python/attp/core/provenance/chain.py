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
                   target_did: str, private_key_path: str) -> dict:
        metadata = metadata.copy()
        session_id = metadata.get("Session_ID")
        hop = metadata.get("Hop")
        hop_count = (hop["Hop_Count"] + 1) if hop else 0
        if hop_count == 0:
            metadata["Origin_DID"] = node_did
        origin_did = metadata.get("Origin_DID")     

        timestamp = time.time()
        hop_hash = calculate_hop_hash(
            content=content,
            node_did=node_did,
            target_did=target_did,
            hop_count=hop_count,
            timestamp=timestamp,
            session_id=session_id,
            origin_did=origin_did,
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
        prev_hop_count: int | None = None,
        timeout: float = 300.0,
    ) -> tuple[bool, str]:
        """校验单条 hop 的字段完整性、类型、值约束、hop_count 递增及超时。

        Args:
            hop: 待校验的 hop 字典。
            prev_hop_count: 上一跳的 Hop_Count，None 则跳过递增校验。
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

        # Step 2: hop_count 递增
        if prev_hop_count is not None:
            expected = prev_hop_count + 1
            if hop["Hop_Count"] != expected:
                return False, (f"[HOP_COUNT_MISMATCH] Expected Hop_Count={expected} "
                               f"(prev+1), got {hop['Hop_Count']}")

        # Step 3: timestamp 超时
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
        origin_did: str,
    ) -> tuple[bool, str]:
        """验证回传 record 与已存储 record 的一致性。

        在源节点 A 调用。对比 A 已存储的上一条回传记录（如来自 B）与
        当前回传节点（如 C）声称的前一跳信息，检测篡改或栽赃行为。

        Args:
            stored_hop: A 已存储的上一条回传 record（如 B 的 hop）。
            prev_hop: 当前回传节点声称收到的上一跳完整信息
                     （对应 record 元数据中的 PrevHop）。
            session_id: 会话标识。
            origin_did: 源 DID。
        Returns:
            (True, "") 验证通过；(False, 错误描述) 验证失败。
        """
        if not prev_hop:
            return True, ""

        if not stored_hop:
            logger.warning("Back-prop: PrevHop present but no stored record")
            return False, "No stored record to verify against"

        #step1: 验证新传入的metadata基本合法性（字段、类型、hop_count递增、超时）
        is_valid, error_msg = self.validate_hop(
            hop=prev_hop,
            prev_hop_count=stored_hop.get("Hop_Count"),
        )
        if not is_valid:
            return False, error_msg

        #step2: 核算stored_hop和新传入的pre_hop哈希值，验证上一跳信息与已存储 record 的一致性
        prev_sign = prev_hop.get("Signature", "")
        prev_node_did = prev_hop.get("node_did", "")

        store_hop_hash = calculate_hop_hash(
            content=stored_hop.get("Content", ""),
            node_did=stored_hop.get("node_did", ""),
            target_did=stored_hop.get("target_did", ""),
            hop_count=stored_hop.get("Hop_Count", 0),
            timestamp=stored_hop.get("Timestamp", 0.0),
            session_id=stored_hop.get("session_id"),
            origin_did=stored_hop.get("origin_did"),
        )

        prev_hop_hash = calculate_hop_hash(
            content=prev_hop.get("Content", ""),
            node_did=prev_node_did,
            target_did=prev_hop.get("target_did", ""),
            hop_count=prev_hop.get("Hop_Count", 0),
            timestamp=prev_hop.get("Timestamp", 0.0),
            session_id=session_id,
            origin_did=origin_did,
        )

        prev_public_key = self._key_store.get(prev_node_did)
        if prev_public_key is None:
            logger.error("Back-prop: No public key for previous node {}", prev_node_did)
            return False, f"No public key for previous node {prev_node_did}"

        step1_ok = verify_signature(prev_hop_hash, prev_sign, prev_public_key)

        # Step 3: 已存储 record 的 Signature == 当前节点声称的上一跳 Signature
        step2_ok = stored_hop.get("Signature") == prev_sign

        # Step 4: 已存储 record 的 Content == 当前节点声称的上一跳 Content
        step3_ok = store_hop_hash == prev_hop_hash

        # 错误分类
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

