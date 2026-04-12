"""核心链逻辑：追加跳和验证。"""

import time

from attp_channel.logging import get_logger
from attp_channel.protocol.authentication import KeyStore
from attp_channel.protocol.authentication import sign_hash, verify_signature
from attp_channel.protocol.provenance import calculate_entry_hash

logger = get_logger("Tracing")


class ChainManager:
    """管理哈希链的追加和验证。"""

    def __init__(self, key_store: KeyStore, storage=None):
        self._key_store = key_store
        self._storage = storage

    def append_hop(self, metadata: dict, content_snapshot: str, node_did: str,
                   target_did: str, private_key_path: str,
                   save_to_db: bool = True) -> dict:
        metadata = metadata.copy()
        session_id = metadata.get("Session_ID")
        if not session_id or session_id == "UNKNOWN_SESSION":
            session_id = f"session_{int(time.time() * 1000)}"
        path = metadata.get("Path", [])

        hop_count = len(path)
        prev_hash = path[-1]["Log"]["Entry_Hash"] if hop_count > 0 else "Genesis"
        timestamp = time.time()

        snapshot = content_snapshot[:100] if content_snapshot else ""

        log_data = {
            "session_id": session_id,
            "hop_count": hop_count,
            "content_snapshot": snapshot,
            "timestamp": timestamp,
            "node_did": node_did,
        }

        entry_hash = calculate_entry_hash(prev_hash, log_data)

        private_key = self._key_store.load_private_key(private_key_path)
        signature = sign_hash(entry_hash, private_key)

        log_entry = {
            "node_did": node_did,
            "target_did": target_did,
            "Entry_Hash": entry_hash,
            "Prev_Hash": prev_hash,
            "Session_ID": session_id,
            "Hop_Count": hop_count,
            "Content_Snapshot": snapshot,
            "Signature": signature,
            "Timestamp": timestamp,
        }

        if save_to_db and self._storage is not None:
            self._storage.save_to_db(
                node_did, target_did, entry_hash, prev_hash,
                session_id, hop_count, snapshot, signature, timestamp,
            )

        metadata["Session_ID"] = session_id

        new_path = list(path)
        new_path.append({"Log": log_entry})
        metadata["Path"] = new_path
        logger.debug("append_hop called with metadata={}", metadata)
        return metadata

    def validate_chain(self, metadata: dict) -> bool:
        path = metadata.get("Path", [])
        if not path:
            return True

        if time.time() - path[-1]["Log"]["Timestamp"] > 300:
            logger.error("Security Alert: Message TTL expired.")
            return False

        for i in range(len(path)):
            curr_log = path[i]["Log"]

            # ---- hash 链检查 ----
            if i >= 1:
                prev_log = path[i - 1]["Log"]
                if curr_log.get("Prev_Hash") != prev_log.get("Entry_Hash"):
                    logger.error(
                        "Security Alert: Broken chain between {} and {}",
                        prev_log.get("node_did"), curr_log.get("node_did"),
                    )
                    return False

            # ---- 重算 hash ----
            recomputed = calculate_entry_hash(curr_log.get("Prev_Hash"), {
                "session_id": curr_log.get("Session_ID"),
                "hop_count": curr_log.get("Hop_Count"),
                "content_snapshot": curr_log.get("Content_Snapshot"),
                "timestamp": curr_log.get("Timestamp"),
                "node_did": curr_log.get("node_did"),
            })
            if recomputed != curr_log.get("Entry_Hash"):
                logger.error(
                    "Security Alert: Hash manipulation detected at node {}",
                    curr_log.get("node_did"),
                )
                return False

            # ---- 签名验证 ----
            signature = curr_log.get("Signature")
            node_did = curr_log.get("node_did")
            if not signature:
                logger.warning(f"No signature at hop {i}, skip sig verify")
                continue

            public_key = self._key_store.get(node_did)
            if public_key is None:
                logger.error(f"Security Alert: No cached public key for {node_did}")
                return False

            if not verify_signature(recomputed, signature, public_key):
                logger.error(f"Security Alert: Signature verification failed at {node_did}")
                return False

        return True

    @staticmethod
    def get_origin_did(metadata: dict) -> str | None:
        """获取 metadata 中 Path 的第一个节点 DID（消息最初发出者）。"""
        path = metadata.get("Path", [])
        if path:
            return path[0]["Log"].get("node_did")
        return None
