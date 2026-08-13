"""Horizontal Axis — 横向分析数据模型（逐跳改版：跨会话确认）。

横轴从「独立 H-Reasoner 全局画像」收窄为「跨会话确认」：纵轴把逐跳分数喂入
per-DID 的 F 累加器，达阈值后横轴取 α 个会话做综合确认，确认则告警、良性则记摘要闭案。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from attp.core.analysis.base_models import EvidenceItem


@dataclass
class CrossSessionProfile:
    """单个 DID 跨多个会话的行为画像（确认时构建，供 prompt 使用）。

    field mapping (作为 sender)：
        field_a_traces → A2T, field_b_traces → A2U, field_c_traces → U2A,
        field_d_traces → A2A, field_e_traces → T2A,
        received_traces → 该 DID 作为 target 接收的消息（上下文参考）
    """

    did: str
    node_type: str
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
class ConfirmationVerdict:
    """横轴确认结论（单 DID）。"""

    did: str
    node_type: str
    confirmed: bool = False          # True = 确认存在跨会话攻击
    severity: str = "none"           # none/low/medium/high/critical
    taint_score: float = 0.0         # [0,10]
    threat_pattern: str = "none"
    evidence: str = ""
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    sessions_reviewed: int = 0
    summary: str = ""                # 本次确认总体结论
    context_summary: str = ""        # 节点档案摘要（良性时写入 dossier）

    def to_dict(self) -> dict[str, Any]:
        return {
            "did": self.did,
            "node_type": self.node_type,
            "confirmed": self.confirmed,
            "severity": self.severity,
            "taint_score": self.taint_score,
            "threat_pattern": self.threat_pattern,
            "evidence": self.evidence,
            "evidence_items": [e.to_dict() for e in self.evidence_items],
            "sessions_reviewed": self.sessions_reviewed,
            "summary": self.summary,
            "context_summary": self.context_summary,
        }


@dataclass
class ConfirmationReport:
    """一次横轴确认的报告（持久化到 horizontal_analysis_reports）。"""

    did: str
    node_type: str
    batch_index: int
    from_trace_id: int
    to_trace_id: int
    sessions_scanned: int             # 实际复核的会话数（α + 高危兜底）
    selected_sessions: list[str] = field(default_factory=list)
    verdict: ConfirmationVerdict | None = None
    overall_verdict: str = "clean"    # clean / suspicious / malicious（代码推导）
    summary: str = ""
    context_summary: str = ""         # 节点档案摘要（良性时写入 dossier）
    triggered_by: str = ""            # "f_threshold" / "manual"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        verdict_dict = self.verdict.to_dict() if self.verdict else {}
        confirmed = self.verdict.confirmed if self.verdict else False
        return {
            "did": self.did,
            "node_type": self.node_type,
            "batch_index": self.batch_index,
            "from_trace_id": self.from_trace_id,
            "to_trace_id": self.to_trace_id,
            "sessions_scanned": self.sessions_scanned,
            "selected_sessions": self.selected_sessions,
            "confirmed": confirmed,
            "verdict": verdict_dict,
            "overall_verdict": self.overall_verdict,
            "summary": self.summary,
            "context_summary": self.context_summary,
            "triggered_by": self.triggered_by,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfirmationReport:
        v = data.get("verdict", {}) or {}
        verdict = ConfirmationVerdict(
            did=v.get("did", data.get("did", "")),
            node_type=v.get("node_type", data.get("node_type", "")),
            confirmed=v.get("confirmed", data.get("confirmed", False)),
            severity=v.get("severity", "none"),
            taint_score=v.get("taint_score", 0.0),
            threat_pattern=v.get("threat_pattern", "none"),
            evidence=v.get("evidence", ""),
            evidence_items=[EvidenceItem.from_dict(e) for e in v.get("evidence_items", [])],
            sessions_reviewed=v.get("sessions_reviewed", data.get("sessions_scanned", 0)),
        )
        return cls(
            did=data.get("did", ""),
            node_type=data.get("node_type", ""),
            batch_index=data.get("batch_index", 0),
            from_trace_id=data.get("from_trace_id", 0),
            to_trace_id=data.get("to_trace_id", 0),
            sessions_scanned=data.get("sessions_scanned", 0),
            selected_sessions=data.get("selected_sessions", []),
            verdict=verdict,
            overall_verdict=data.get("overall_verdict", "clean"),
            summary=data.get("summary", ""),
            context_summary=data.get("context_summary", ""),
            triggered_by=data.get("triggered_by", ""),
            timestamp=data.get("timestamp", time.time()),
        )
