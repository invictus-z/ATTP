"""AppSession — App 层 per-chat_id 路由元数据容器。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppSession:
    """App 层 session：追踪消息路由元数据（recorded_hop / protocol_url）。"""

    key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    # -- trace routing metadata --

    def get_trace_metadata(self) -> dict[str, Any]:
        """Extract trace-related keys from metadata."""
        keys = ("recorded_hop", "protocol_url")
        return {k: self.metadata[k] for k in keys if k in self.metadata}

    def set_trace_metadata(self, trace_data: dict[str, Any]) -> None:
        """Merge trace keys into metadata."""
        for k in ("recorded_hop", "protocol_url"):
            if k in trace_data:
                self.metadata[k] = trace_data[k]
        self.updated_at = time.time()

    # -- generic metadata --

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self.updated_at = time.time()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    def update_metadata(self, data: dict[str, Any]) -> None:
        """Bulk-merge *data* into metadata."""
        self.metadata.update(data)
        self.updated_at = time.time()
