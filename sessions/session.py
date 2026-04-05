"""Session – per-chat_id metadata container."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    """Holds metadata for a single chat session."""

    key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def get_trace_metadata(self) -> dict[str, Any]:
        """Extract trace-related keys (Path, Session_ID) from metadata."""
        return {k: self.metadata[k] for k in ("Path", "Session_ID") if k in self.metadata}

    def set_trace_metadata(self, trace_data: dict[str, Any]) -> None:
        """Merge trace keys into metadata."""
        for k in ("Path", "Session_ID"):
            if k in trace_data:
                self.metadata[k] = trace_data[k]
        self.updated_at = time.time()

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self.updated_at = time.time()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)
