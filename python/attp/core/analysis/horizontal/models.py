"""Horizontal Axis — 横向分析数据模型。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attp.core.analysis.base_models import EvidenceItem


@dataclass
class CrossSessionProfile:
    """Single DID 的跨多个 Session 行为画像。

    field mapping (作为 sender):
        field_a_traces → A2T (Agent→Tool)
        field_b_traces → A2U (Agent→User)
        field_c_traces → U2A (User→Agent)
        field_d_traces → A2A (Agent→Agent)
        field_e_traces → T2A (Tool→Agent)
        received_traces → 该DID作为target接收到的消息（上下文参考）
    """

    did: str
    node_type: str                              # agent / tool / user
    sessions_involved: list[str] = field(default_factory=list)
    field_a_traces: list[dict] = field(default_factory=list)
    field_b_traces: list[dict] = field(default_factory=list)
    field_c_traces: list[dict] = field(default_factory=list)
    field_d_traces: list[dict] = field(default_factory=list)
    field_e_traces: list[dict] = field(default_factory=list)
    received_traces: list[dict] = field(default_factory=list)
    time_span: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "did": self.did,
            "node_type": self.node_type,
            "sessions_involved": self.sessions_involved,
            "field_a_traces": self.field_a_traces,
            "field_b_traces": self.field_b_traces,
            "field_c_traces": self.field_c_traces,
            "field_d_traces": self.field_d_traces,
            "field_e_traces": self.field_e_traces,
            "received_traces": self.received_traces,
        }
        if self.time_span:
            d["time_span"] = list(self.time_span)
        return d


@dataclass
class DIDVerdict:
    """Single DID 的跨Session全局判定。"""

    did: str
    node_type: str
    sessions_analyzed: int
    aligned: bool = True
    deviation_type: str = "none"
    threat_pattern: str = "none"
    evidence: str = ""
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    severity: str = "none"
    taint_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "did": self.did,
            "node_type": self.node_type,
            "sessions_analyzed": self.sessions_analyzed,
            "aligned": self.aligned,
            "deviation_type": self.deviation_type,
            "threat_pattern": self.threat_pattern,
            "evidence": self.evidence,
            "evidence_items": [e.to_dict() for e in self.evidence_items],
            "severity": self.severity,
            "taint_score": self.taint_score,
        }


@dataclass
class HorizontalTaintReport:
    """Cross-session global analysis report for a single DID."""

    did: str
    node_type: str
    batch_index: int
    from_trace_id: int
    to_trace_id: int
    sessions_scanned: int
    did_verdict: DIDVerdict
    overall_verdict: str = "clean"
    summary: str = ""
    context_summary: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "did": self.did,
            "node_type": self.node_type,
            "batch_index": self.batch_index,
            "from_trace_id": self.from_trace_id,
            "to_trace_id": self.to_trace_id,
            "sessions_scanned": self.sessions_scanned,
            "did_verdict": self.did_verdict.to_dict(),
            "overall_verdict": self.overall_verdict,
            "summary": self.summary,
            "context_summary": self.context_summary,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HorizontalTaintReport:
        dv = data.get("did_verdict", {})
        verdict = DIDVerdict(
            did=dv.get("did", ""),
            node_type=dv.get("node_type", ""),
            sessions_analyzed=dv.get("sessions_analyzed", 0),
            aligned=dv.get("aligned", True),
            deviation_type=dv.get("deviation_type", "none"),
            threat_pattern=dv.get("threat_pattern", "none"),
            evidence=dv.get("evidence", ""),
            evidence_items=[EvidenceItem.from_dict(e) for e in dv.get("evidence_items", [])],
            severity=dv.get("severity", "none"),
            taint_score=dv.get("taint_score", 0.0),
        )
        return cls(
            did=data.get("did", ""),
            node_type=data.get("node_type", ""),
            batch_index=data.get("batch_index", 0),
            from_trace_id=data.get("from_trace_id", 0),
            to_trace_id=data.get("to_trace_id", 0),
            sessions_scanned=data.get("sessions_scanned", 0),
            did_verdict=verdict,
            overall_verdict=data.get("overall_verdict", "clean"),
            summary=data.get("summary", ""),
            context_summary=data.get("context_summary", ""),
            timestamp=data.get("timestamp", time.time()),
        )
