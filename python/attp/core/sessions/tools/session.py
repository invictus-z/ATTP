"""ToolSession — 工具节点侧 per-session 状态容器。

跟踪活跃工具调用（nonce → 请求映射）、protocol_node_address、
hop_count 等状态，用于工具节点侧的 ATTP 回传流程。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSession:
    """工具节点侧 session：跟踪活跃工具调用和 nonce 匹配。"""

    key: str
    protocol_node_address: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    # -- nonce-based pending request storage --

    def store_pending_request(self, nonce: str, request_info: dict[str, Any]) -> None:
        """暂存待处理的工具调用请求，以 nonce 为 key。"""
        self.metadata[f"_pending_req:{nonce}"] = request_info
        self.updated_at = time.time()

    def get_pending_request(self, nonce: str) -> dict[str, Any] | None:
        """检索待处理请求。"""
        return self.metadata.get(f"_pending_req:{nonce}")

    def remove_pending_request(self, nonce: str) -> None:
        """移除已处理的请求。"""
        self.metadata.pop(f"_pending_req:{nonce}", None)

    # -- hop count tracking --

    def get_last_hop_count(self) -> list[int] | None:
        """获取最近一次完成的 hop_count。"""
        return self.metadata.get("_last_hop_count")

    def set_last_hop_count(self, hc: list[int]) -> None:
        """记录最近一次完成的 hop_count。"""
        self.metadata["_last_hop_count"] = hc
        self.updated_at = time.time()

    # -- protocol node address --

    def set_protocol_node_address(self, address: str) -> None:
        """设置协议节点地址。"""
        self.protocol_node_address = address
        self.updated_at = time.time()

    # -- generic metadata --

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self.updated_at = time.time()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)