"""
BehaviorEntry — 单条行为记录。

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
