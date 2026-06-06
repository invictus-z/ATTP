"""Vertical Axis — 纵向分析数据模型。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attp.core.analysis.base_models import EvidenceItem


@dataclass
class NodeBehaviorProfile:
    """Aggregated behavior profile for one node at one hop.

    field mapping:
        field_a → A2T (Agent→Tool)
        field_b → A2U (Agent→User)
        field_c → U2A (User→Agent)
        field_d → A2A (Agent→Agent)
        field_e → T2A (Tool→Agent)
    """

    node_did: str
    hop_count: list[int]
    field_a: list[dict] = field(default_factory=list)
    field_b: list[dict] = field(default_factory=list)
    field_c: list[dict] = field(default_factory=list)
    field_d: list[dict] = field(default_factory=list)
    field_e: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_did": self.node_did,
            "hop_count": self.hop_count,
            "field_a": self.field_a,
            "field_b": self.field_b,
            "field_c": self.field_c,
            "field_d": self.field_d,
            "field_e": self.field_e,
        }


@dataclass
class NodeTaintVerdict:
    """Analysis verdict for a single node."""

    node_did: str
    hop_count: list[int]
    aligned: bool = True
    deviation_type: str = "none"
    influence_detected: bool = False
    influence_type: str = "none"
    evidence: str = ""
    evidence_items: list[EvidenceItem] = field(default_factory=list)
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
            "evidence_items": [e.to_dict() for e in self.evidence_items],
            "severity": self.severity,
            "taint_score": self.taint_score,
        }


@dataclass
class VerticalTaintReport:
    """Complete vertical analysis report for one batch of records."""

    session_id: str
    batch_index: int
    from_trace_id: int
    to_trace_id: int
    node_verdicts: list[NodeTaintVerdict] = field(default_factory=list)
    overall_verdict: str = "clean"  # clean / suspicious / malicious
    summary: str = ""
    context_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    # Cross-Lock: 本次分析涉及的所有 node_did（用于触发横向累积）
    analyzed_dids: list[str] = field(default_factory=list)

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
            "analyzed_dids": self.analyzed_dids,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerticalTaintReport:
        verdicts = []
        for v in data.get("node_verdicts", []):
            items = [EvidenceItem.from_dict(e) for e in v.get("evidence_items", [])]
            verdicts.append(NodeTaintVerdict(
                node_did=v.get("node_did", ""),
                hop_count=v.get("hop_count", [0, 0]),
                aligned=v.get("aligned", True),
                deviation_type=v.get("deviation_type", "none"),
                influence_detected=v.get("influence_detected", False),
                influence_type=v.get("influence_type", "none"),
                evidence=v.get("evidence", ""),
                evidence_items=items,
                severity=v.get("severity", "none"),
                taint_score=v.get("taint_score", 0.0),
            ))
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
            analyzed_dids=data.get("analyzed_dids", []),
        )
