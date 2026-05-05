"""
NodeMessage — 行为溯源数据结构。

field_type 取值：
  A2T — Agent → Tool   （Agent 调用工具）
  A2U — Agent → User   （Agent 发给用户）
  U2A — User  → Agent  （用户发给 Agent）
  A2A — Agent → Agent  （Agent 间通信）
  T2A — Tool  → Agent  （工具返回结果，预留）
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BehaviorEntry:
    """单条行为记录。"""

    field_type: str  # "A2T" / "A2U" / "U2A" / "A2A" / "T2A"
    content: str
    timestamp: float = field(default_factory=time.time)
    target: str = ""  # a: tool; d: target_did; b/c: ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_type": self.field_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "target": self.target,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BehaviorEntry:
        return cls(
            field_type=data["field_type"],
            content=data["content"],
            timestamp=data.get("timestamp", 0.0),
            target=data.get("target", ""),
            extra=data.get("extra", {}),
        )


@dataclass
class NodeMessage:
    """一个节点在一次 hop 中记录的所有行为。"""

    node_did: str
    session_id: str
    hop_count: int
    origin_did: str = ""
    entries: list[BehaviorEntry] = field(default_factory=list)

    def add_entry(
        self,
        field_type: str,
        content: str,
        target: str = "",
        **extra: Any,
    ) -> None:
        self.entries.append(
            BehaviorEntry(
                field_type=field_type,
                content=content,
                target=target,
                extra=extra,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_did": self.node_did,
            "session_id": self.session_id,
            "hop_count": self.hop_count,
            "origin_did": self.origin_did,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NodeMessage:
        entries = [BehaviorEntry.from_dict(e) for e in data.get("entries", [])]
        return cls(
            node_did=data["node_did"],
            session_id=data["session_id"],
            hop_count=data["hop_count"],
            origin_did=data.get("origin_did", ""),
            entries=entries,
        )
