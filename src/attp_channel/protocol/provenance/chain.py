"""核心链逻辑：追加跳和验证。"""

import time

from attp_channel.logging import get_logger
from attp_channel.protocol.authentication import KeyStore
from attp_channel.protocol.authentication import sign_hash, verify_signature
from attp_channel.protocol.provenance import calculate_genesis_hash, calculate_hop_hash

logger = get_logger("Tracing")


class ChainManager:
    """管理消息跳的追加和验证。"""

    def __init__(self, key_store: KeyStore, storage=None):
        self._key_store = key_store
        self._storage = storage

    def append_hop(self, metadata: dict, content: str, node_did: str,
                   target_did: str, private_key_path: str,
                   save_to_db: bool = True) -> dict:
        metadata = metadata.copy()
        session_id = metadata.get("Session_ID")
        if not session_id or session_id == "UNKNOWN_SESSION":
            session_id = f"session_{int(time.time() * 1000)}"

        latest_hop = metadata.get("Latest_Hop")
        hop_count = (latest_hop["Hop_Count"] + 1) if latest_hop else 0

        timestamp = time.time()
        hop_hash = calculate_hop_hash(
            content=content,
            node_did=node_did,
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
            "Content": content[:100],
        }

        # 创世节点：设置 Origin_DID 和 Genesis_Signature
        if hop_count == 0:
            metadata["Origin_DID"] = node_did
            genesis_hash = calculate_genesis_hash(session_id, node_did)
            metadata["Genesis_Signature"] = sign_hash(genesis_hash, private_key)
        else:
            metadata["Origin_DID"] = metadata.get("Origin_DID", "")
            metadata["Genesis_Signature"] = metadata.get("Genesis_Signature", "")

        origin_did = metadata.get("Origin_DID", "")
        genesis_signature = metadata.get("Genesis_Signature", "")

        if save_to_db and self._storage is not None:
            self._storage.save_to_db(
                node_did, target_did, session_id, hop_count,
                signature, timestamp, origin_did, genesis_signature,
                content[:100],
            )

        metadata["Session_ID"] = session_id
        metadata["Latest_Hop"] = new_log_entry
        logger.debug("append_hop called with metadata={}", metadata)
        return metadata

    def validate_chain(self, metadata: dict, content: str) -> bool:
        latest = metadata.get("Latest_Hop")

        if not latest:
            return True

        # TTL 检查
        if time.time() - latest["Timestamp"] > 300:
            logger.error("Security Alert: Message TTL expired.")
            return False

        # Genesis 签名验证：确认 session_id 和 origin_did 未被篡改
        origin_did = metadata.get("Origin_DID")
        genesis_signature = metadata.get("Genesis_Signature")
        session_id = metadata.get("Session_ID")

        if origin_did and genesis_signature:
            genesis_hash = calculate_genesis_hash(session_id, origin_did)
            genesis_pub_key = self._key_store.get(origin_did)
            if genesis_pub_key is None:
                logger.error(f"Security Alert: No cached public key for origin {origin_did}")
                return False
            if not verify_signature(genesis_hash, genesis_signature, genesis_pub_key):
                logger.error("Security Alert: Genesis signature verification failed")
                return False
        else:
            logger.error("Security Alert: Missing Origin_DID or Genesis_Signature")
            return False

        # Latest_Hop 身份验证
        hop_hash = calculate_hop_hash(
            content=content,
            node_did=latest["node_did"],
            target_did=latest["target_did"],
            hop_count=latest["Hop_Count"],
            timestamp=latest["Timestamp"],
            session_id=session_id,
        )
        signature = latest.get("Signature")
        if not signature:
            logger.error("Security Alert: Missing Signature in Latest_Hop")
            return False

        node_did = latest["node_did"]
        public_key = self._key_store.get(node_did)
        if public_key is None:
            logger.error(f"Security Alert: No cached public key for {node_did}")
            return False
        if not verify_signature(hop_hash, signature, public_key):
            logger.error(f"Security Alert: Signature failed for {node_did}")
            return False

        return True

    @staticmethod
    def get_origin_did(metadata: dict) -> str | None:
        """获取 metadata 中消息最初发出者的 DID。"""
        return metadata.get("Origin_DID")
