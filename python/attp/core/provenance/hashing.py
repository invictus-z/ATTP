"""哈希计算：genesis 标识哈希和每跳签名哈希。"""

import json
import hashlib


def calculate_genesis_hash(session_id: str, protocol_node_address: str) -> str:
    """计算创世标识的 SHA-256 哈希，用于防篡改验证。"""
    raw = json.dumps({
        "session_id": session_id,
        "protocol_node_address": protocol_node_address,
    }, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_hop_hash(
    content: str,
    node_did: str,
    target_did: str,
    hop_count: int,
    timestamp: float,
    session_id: str,
    protocol_node_address: str,
) -> str:
    """计算单跳消息字段的 SHA-256 哈希，用于身份验证签名。"""
    raw = json.dumps({
        "content": content,
        "node_did": node_did,
        "target_did": target_did,
        "hop_count": hop_count,
        "timestamp": timestamp,
        "session_id": session_id,
        "protocol_node_address": protocol_node_address,
    }, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
