"""Data models for semantic taint analysis."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class IntentDescriptor:
    """Structured user intent extracted from the original task (field c)."""

    original_task: str
    core_objective: str
    constraints: list[str] = field(default_factory=list)
    involved_capabilities: list[str] = field(default_factory=list)
    risk_level: str = "medium"  # low / medium / high

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_task": self.original_task,
            "core_objective": self.core_objective,
            "constraints": self.constraints,
            "involved_capabilities": self.involved_capabilities,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentDescriptor:
        return cls(
            original_task=data["original_task"],
            core_objective=data["core_objective"],
            constraints=data.get("constraints", []),
            involved_capabilities=data.get("involved_capabilities", []),
            risk_level=data.get("risk_level", "medium"),
        )


@dataclass
class NodeBehaviorProfile:
    """Aggregated behavior profile for one node at one hop."""

    node_did: str
    hop_count: int
    field_a: list[dict] = field(default_factory=list)
    field_b: list[dict] = field(default_factory=list)
    field_d: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_did": self.node_did,
            "hop_count": self.hop_count,
            "field_a": self.field_a,
            "field_b": self.field_b,
            "field_d": self.field_d,
        }


@dataclass
class NodeTaintVerdict:
    """Analysis verdict for a single node."""

    node_did: str
    hop_count: int
    aligned: bool = True
    deviation_type: str = "none"
    influence_detected: bool = False
    influence_type: str = "none"
    evidence: str = ""
    severity: str = "none"
    taint_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_did": self.node_did,
            "hop_count": self.hop_count,
            "aligned": self.aligned,
            "deviation_type": self.deviation_type,
            "influence_detected": self.influence_detected,
            "influence_type": self.influence_type,
            "evidence": self.evidence,
            "severity": self.severity,
            "taint_score": self.taint_score,
        }


@dataclass
class TaintReport:
    """Complete analysis report for one batch of records."""

    session_id: str
    batch_index: int
    from_trace_id: int
    to_trace_id: int
    node_verdicts: list[NodeTaintVerdict] = field(default_factory=list)
    overall_verdict: str = "clean"  # clean / suspicious / malicious
    summary: str = ""
    context_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "batch_index": self.batch_index,
            "from_trace_id": self.from_trace_id,
            "to_trace_id": self.to_trace_id,
            "node_verdicts": [v.to_dict() for v in self.node_verdicts],
            "overall_verdict": self.overall_verdict,
            "summary": self.summary,
            "context_summary": self.context_summary,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaintReport:
        verdicts = [NodeTaintVerdict(**v) for v in data.get("node_verdicts", [])]
        return cls(
            session_id=data["session_id"],
            batch_index=data.get("batch_index", 0),
            from_trace_id=data.get("from_trace_id", 0),
            to_trace_id=data.get("to_trace_id", 0),
            node_verdicts=verdicts,
            overall_verdict=data.get("overall_verdict", "clean"),
            summary=data.get("summary", ""),
            context_summary=data.get("context_summary", ""),
            timestamp=data.get("timestamp", time.time()),
        )
