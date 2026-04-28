"""Session – per-chat_id metadata container."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attp_channel.sessions.node_message import NodeMessage


@dataclass
class Session:
    """Holds metadata for a single chat session."""

    key: str
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def get_trace_metadata(self) -> dict[str, Any]:
        """Extract trace-related keys from metadata."""
        keys = ("Hop", "Session_ID", "Origin_DID")
        return {k: self.metadata[k] for k in keys if k in self.metadata}

    def set_trace_metadata(self, trace_data: dict[str, Any]) -> None:
        """Merge trace keys into metadata."""
        for k in ("Hop", "Session_ID", "Origin_DID"):
            if k in trace_data:
                self.metadata[k] = trace_data[k]
        self.updated_at = time.time()

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value
        self.updated_at = time.time()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    def update_metadata(self, data: dict[str, Any]) -> None:
        """Bulk-merge *data* into metadata."""
        self.metadata.update(data)
        self.updated_at = time.time()

    # -- NodeMessage management --

    def _current_hop_count(self) -> int:
        """Derive the current hop_count from existing trace metadata."""
        latest = self.metadata.get("Hop")
        return (latest["Hop_Count"] + 1) if latest else 0

    def get_or_create_node_message(
        self,
        node_did: str,
        origin_did: str = "",
        hop_count: int | None = None,
    ) -> NodeMessage:
        """Get or create the NodeMessage for the given hop."""
        if hop_count is None:
            hop_count = self._current_hop_count()
        store_key = f"node_msg_{hop_count}"
        nm = self.metadata.get(store_key)
        if not isinstance(nm, NodeMessage):
            nm = NodeMessage(
                node_did=node_did,
                session_id=self.key,
                hop_count=hop_count,
                origin_did=origin_did,
            )
            self.metadata[store_key] = nm
        if origin_did and not nm.origin_did:
            nm.origin_did = origin_did
        return nm

    def get_node_message(self, hop_count: int) -> NodeMessage | None:
        """Retrieve the NodeMessage for a given hop."""
        nm = self.metadata.get(f"node_msg_{hop_count}")
        return nm if isinstance(nm, NodeMessage) else None

    # -- Analysis state tracking --

    def get_analysis_state(self) -> dict[str, Any]:
        """Get analysis-related state from metadata."""
        return {
            "report_count": self.metadata.get("_analysis_report_count", 0),
            "last_trace_id": self.metadata.get("_analysis_last_trace_id", 0),
            "batch_index": self.metadata.get("_analysis_batch_index", 0),
            "context": self.metadata.get("_analysis_context", ""),
            "intent": self.metadata.get("_analysis_intent"),
        }

    def increment_report_count(self) -> int:
        """Increment and return the unchecked report count."""
        count = self.metadata.get("_analysis_report_count", 0) + 1
        self.metadata["_analysis_report_count"] = count
        self.updated_at = time.time()
        return count

    def reset_report_count(self) -> None:
        """Reset the unchecked report count to 0."""
        self.metadata["_analysis_report_count"] = 0
        self.updated_at = time.time()

    def update_analysis_cursor(
        self, batch_index: int, last_trace_id: int, context: str,
    ) -> None:
        """Update the analysis cursor after a successful analysis run."""
        self.metadata["_analysis_batch_index"] = batch_index
        self.metadata["_analysis_last_trace_id"] = last_trace_id
        self.metadata["_analysis_context"] = context
        self.updated_at = time.time()

    def set_intent(self, intent: dict) -> None:
        """Store extracted intent descriptor."""
        self.metadata["_analysis_intent"] = intent
        self.updated_at = time.time()

    def get_intent(self) -> dict | None:
        """Retrieve stored intent descriptor, if any."""
        return self.metadata.get("_analysis_intent")
