"""PendingMessage — nonce 匹配的暂存消息数据结构，用于 Branch A 暂存。"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class PendingMessage:
    """通过 nonce 暂存在 Session 中的消息记录。

    当回传1（发送方）的 record 先到达协议节点时，以 nonce 为 key
    暂存该消息。待回传2（接收方）的 record 到达后，通过 nonce 匹配
    进行交叉验证。
    """

    hop: dict               # 完整 hop 记录
    session_id: str
    protocol_node_address: str
    sender_did: str
    sender_node_type: str   # "agent" / "tool" / "user"
    nonce: str
    stored_at: float        # time.time()
    ttl_seconds: float = 300.0
    # -- 身份验证扩展字段（Branch A 填入，Branch B 使用） --
    node_did: str = ""                       # BackMessage.node_did（回传者身份）
    identity_public_key_pem: str | None = None  # 已解析的公钥 PEM
    identity_verified: bool = False          # Branch A 中身份签名是否验证通过

    def is_expired(self) -> bool:
        return time.time() - self.stored_at > self.ttl_seconds

    def to_dict(self) -> dict:
        return {
            "hop": self.hop,
            "session_id": self.session_id,
            "protocol_node_address": self.protocol_node_address,
            "sender_did": self.sender_did,
            "sender_node_type": self.sender_node_type,
            "nonce": self.nonce,
            "stored_at": self.stored_at,
            "ttl_seconds": self.ttl_seconds,
            "node_did": self.node_did,
            "identity_public_key_pem": self.identity_public_key_pem,
            "identity_verified": self.identity_verified,
        }

    @classmethod
    def from_dict(cls, data: dict) -> PendingMessage:
        return cls(
            hop=data["hop"],
            session_id=data["session_id"],
            protocol_node_address=data["protocol_node_address"],
            sender_did=data["sender_did"],
            sender_node_type=data["sender_node_type"],
            nonce=data["nonce"],
            stored_at=data["stored_at"],
            ttl_seconds=data.get("ttl_seconds", 300.0),
            node_did=data.get("node_did", ""),
            identity_public_key_pem=data.get("identity_public_key_pem"),
            identity_verified=data.get("identity_verified", False),
        )
