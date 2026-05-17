"""events.messages — 消息格式规范化。

RecordedHop: 单跳记录内容（嵌入 NodeMessage / BackMessage）
NodeMessage:  转发消息（A → B）
BackMessage: 节点回传消息（A / B 向协议节点回传）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from attp.core.authentication.signatures import sign_hash, verify_signature


# ---------------------------------------------------------------------------
# RecordedHop — 单跳记录
# ---------------------------------------------------------------------------

@dataclass
class RecordedHop:
    """单跳记录内容，嵌入在 NodeMessage 和 BackMessage 中。

    sig_content 是对其余字段哈希后的签名，
    由发送方私钥签署，用于内容完整性验证。
    """

    session_id: str
    sender_did: str
    target_did: str
    content: str
    timestamp: float
    hop_count: list[int]
    sig_content: str = ""

    def content_hash(self) -> str:
        """计算除 sig_content 外所有字段的 SHA-256 哈希。"""
        raw = json.dumps({
            "session_id": self.session_id,
            "sender_did": self.sender_did,
            "target_did": self.target_did,
            "content": self.content,
            "timestamp": self.timestamp,
            "hop_count": self.hop_count,
        }, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "sender_did": self.sender_did,
            "target_did": self.target_did,
            "content": self.content,
            "timestamp": self.timestamp,
            "hop_count": self.hop_count,
            "sig_content": self.sig_content,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordedHop:
        return cls(
            session_id=data["session_id"],
            sender_did=data["sender_did"],
            target_did=data["target_did"],
            content=data["content"],
            timestamp=data["timestamp"],
            hop_count=data["hop_count"],
            sig_content=data.get("sig_content", ""),
        )


# ---------------------------------------------------------------------------
# NodeMessage — 节点间转发消息 (A → B)
# ---------------------------------------------------------------------------

@dataclass
class NodeMessage:
    """转发消息：A 向 B 发送。

    Fields:
        protocol_url:  协议节点地址
        nonce:         唯一标识，用于匹配回传消息
        recorded_hop:  单跳记录内容
    """

    protocol_url: str
    nonce: str
    recorded_hop: RecordedHop

    def sign_content(self, private_key) -> None:
        """发送方私钥对 recorded_hop 内容签名，写入 sig_content。"""
        self.recorded_hop.sig_content = sign_hash(
            self.recorded_hop.content_hash(), private_key,
        )

    def verify_content(self, public_key) -> bool:
        """验证 recorded_hop.sig_content 是否由对应公钥签署。"""
        if not self.recorded_hop.sig_content:
            return False
        return verify_signature(
            self.recorded_hop.content_hash(),
            self.recorded_hop.sig_content,
            public_key,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_url": self.protocol_url,
            "nonce": self.nonce,
            "recorded_hop": self.recorded_hop.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeMessage:
        return cls(
            protocol_url=data["protocol_url"],
            nonce=data["nonce"],
            recorded_hop=RecordedHop.from_dict(data["recorded_hop"]),
        )


# ---------------------------------------------------------------------------
# BackMessage — 节点回传消息
# ---------------------------------------------------------------------------

def _identity_hash(node_did: str, nonce: str) -> str:
    raw = json.dumps({"node_did": node_did, "nonce": nonce}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass
class BackMessage:
    """节点回传消息：节点（A 或 B）向协议节点回传。

    Fields:
        protocol_url:  协议节点地址
        node_did:      回传节点的 DID 身份
        nonce:         唯一标识，用于匹配回传消息
        sig_identity:  node_did + nonce 的私钥签名，用于身份确认
        recorded_hop:  单跳记录内容
    """

    protocol_url: str
    node_did: str
    nonce: str
    sig_identity: str
    recorded_hop: RecordedHop

    # -- 身份签名 --

    def sign_identity(self, private_key) -> None:
        """使用回传节点私钥对 node_did+nonce 签名，写入 sig_identity。"""
        self.sig_identity = sign_hash(
            _identity_hash(self.node_did, self.nonce), private_key,
        )

    def verify_identity(self, public_key) -> bool:
        """验证 sig_identity 是否合法。"""
        if not self.sig_identity:
            return False
        return verify_signature(
            _identity_hash(self.node_did, self.nonce),
            self.sig_identity,
            public_key,
        )

    # -- 内容签名（发送方签名，由 recorded_hop.sig_content 承载）--

    def sign_content(self, private_key) -> None:
        """使用发送方私钥对 recorded_hop 内容签名。"""
        self.recorded_hop.sig_content = sign_hash(
            self.recorded_hop.content_hash(), private_key,
        )

    def verify_content(self, public_key) -> bool:
        """验证 recorded_hop 内容签名（发送方签名）。"""
        if not self.recorded_hop.sig_content:
            return False
        return verify_signature(
            self.recorded_hop.content_hash(),
            self.recorded_hop.sig_content,
            public_key,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_url": self.protocol_url,
            "node_did": self.node_did,
            "nonce": self.nonce,
            "sig_identity": self.sig_identity,
            "recorded_hop": self.recorded_hop.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackMessage:
        return cls(
            protocol_url=data["protocol_url"],
            node_did=data["node_did"],
            nonce=data["nonce"],
            sig_identity=data.get("sig_identity", ""),
            recorded_hop=RecordedHop.from_dict(data["recorded_hop"]),
        )
