"""节点 Entry_Hash 计算。"""

import json
import hashlib


def calculate_entry_hash(prev_hash: str, log_data: dict) -> str:
    """计算单跳的 SHA-256 entry hash。"""
    raw_data = json.dumps({
        "prev_hash": prev_hash,
        "session_id": log_data.get("session_id"),
        "hop_count": log_data.get("hop_count"),
        "content_snapshot": log_data.get("content_snapshot"),
        "timestamp": log_data.get("timestamp"),
        "node_did": log_data.get("node_did"),
    }, sort_keys=True)
    return hashlib.sha256(raw_data.encode("utf-8")).hexdigest()
