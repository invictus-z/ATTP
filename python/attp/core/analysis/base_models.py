"""Cross-Lock Intent Tracking — 共享基础数据模型与评分常量。

改版（逐跳有状态）后的共享类型：
- ``IntentRevision`` — 单条 U2A 抽出的意图增量 Δ（goal/constraints/prohibitions + source）。
- ``HopScore`` — 单跳 V-Reasoner 评分结果（s_i + 4 维 + breadth + severity + evidence + h_i）。
- ``EvidenceItem`` — 纵横共用的证据条目。

评分量纲与分档常量（§6）：taint_score 取 [0,10]，0.5 步进，5 档 severity。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ======================================================================
# 评分量纲与分档（§6）
# ======================================================================

#: 分数步进（0.5，21 档）。
SCORE_STEP = 0.5
#: 分数上限。
SCORE_MAX = 10.0

#: 4 个正交评分维度（顺序即 dim1..dim4）。
DIMENSION_NAMES: tuple[str, ...] = (
    "intent_alignment",      # d1 意图对齐
    "capability",            # d2 能力域 / 越权
    "injection_manipulation",  # d3 注入与操纵
    "exfiltration_tampering",  # d4 外泄与篡改
)
NUM_DIMENSIONS = len(DIMENSION_NAMES)

#: severity 分档上界（左闭右开，最后一档闭区间）。
_SEVERITY_BANDS: tuple[tuple[float, str], ...] = (
    (1.5, "none"),
    (3.5, "low"),
    (5.5, "medium"),
    (7.5, "high"),
    (float("inf"), "critical"),
)
SEVERITY_ORDER: tuple[str, ...] = ("none", "low", "medium", "high", "critical")
SEVERITY_RANK: dict[str, int] = {name: i for i, name in enumerate(SEVERITY_ORDER)}

#: high 档下沿（用于 breadth 统计：维度分超过 medium 即 ≥ 此值）。
SEVERITY_HIGH_LOWER = 5.5
#: critical 档下沿。
SEVERITY_CRITICAL_LOWER = 7.5


def severity_for_score(score: float) -> str:
    """由 [0,10] 分数推导 severity 档（代码推导，不让 LLM 下）。"""
    for upper, name in _SEVERITY_BANDS:
        if score < upper:
            return name
    return "critical"


def overall_verdict_for_severities(severities: list[str]) -> str:
    """由一组跳 severity 推导会话级 overall_verdict（§6.5）。

    任一跳 critical → malicious；任一跳 high → suspicious；否则 clean。
    """
    ranks = [SEVERITY_RANK.get(s, 0) for s in severities]
    if not ranks:
        return "clean"
    top = max(ranks)
    # critical(4) → malicious；high(3) → suspicious
    if top >= SEVERITY_RANK["critical"]:
        return "malicious"
    if top >= SEVERITY_RANK["high"]:
        return "suspicious"
    return "clean"


def aggregate_score(dims: list[float], p: str | float = "max") -> float:
    """聚合 4 维分为单跳总分 s_i（§6.3）。

    - ``"max"``（默认）：取最大维，任一维突出即决定总分，单点高分不被稀释。
    - ``"sum"``：加权和（会稀释，作基线）。
    - 数值 p：L^p 范数 ``(Σ d_k^p)^(1/p)``。
    """
    if not dims:
        return 0.0
    if p == "max":
        return max(dims)
    if p == "sum":
        return sum(dims) / len(dims)
    pp = float(p)
    if pp <= 0:
        return max(dims)
    return (sum(d ** pp for d in dims)) ** (1.0 / pp)


def compute_breadth(dims: list[float]) -> int:
    """统计超过 medium（≥ SEVERITY_HIGH_LOWER）的维度数（§6.4，仅归因用）。"""
    return sum(1 for d in dims if d >= SEVERITY_HIGH_LOWER)


# ======================================================================
# IntentRevision — 意图增量 Δ（逐条追加）
# ======================================================================

@dataclass
class IntentRevisionSource:
    """意图增量的来源（哪条 U2A、DID、时间），单独记录供回放，不作为意图字段。"""

    trace_id: int = 0
    did: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "did": self.did,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> IntentRevisionSource | None:
        if not data:
            return None
        return cls(
            trace_id=data.get("trace_id", 0),
            did=data.get("did", ""),
            timestamp=data.get("timestamp", 0.0),
        )


@dataclass
class IntentRevision:
    """单条 U2A 抽出的意图增量 Δ_i = {goal, constraints, prohibitions}。

    意图流 I = [Δ_0, ..., Δ_m] 只增不改，由发起者 DID 的每条 U2A 追加。
    """

    goal: str
    constraints: list[str] = field(default_factory=list)
    prohibitions: list[str] = field(default_factory=list)
    source: IntentRevisionSource | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "constraints": self.constraints,
            "prohibitions": self.prohibitions,
            "source": self.source.to_dict() if self.source else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IntentRevision:
        return cls(
            goal=data.get("goal", ""),
            constraints=data.get("constraints", []),
            prohibitions=data.get("prohibitions", []),
            source=IntentRevisionSource.from_dict(data.get("source")),
        )


# ======================================================================
# HopScore — 单跳评分结果
# ======================================================================

@dataclass
class HopScore:
    """V-Reasoner 对单条动作跳的评分结果。

    score 即 s_i∈[0,10]（聚合 4 维后）；dimensions 为 [d1,d2,d3,d4]；
    hidden_state 为本跳产出的滚动隐状态 h_i（复用 context_summary）。
    """

    trace_id: int
    session_id: str
    sender_did: str
    field_type: str
    hop_count: list[int]
    score: float
    dimensions: list[float] = field(default_factory=list)
    breadth: int = 0
    severity: str = "none"
    deviation_type: str = "none"
    evidence_items: list[EvidenceItem] = field(default_factory=list)
    hidden_state: str = ""
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "sender_did": self.sender_did,
            "field_type": self.field_type,
            "hop_count": self.hop_count,
            "score": self.score,
            "dimensions": self.dimensions,
            "breadth": self.breadth,
            "severity": self.severity,
            "deviation_type": self.deviation_type,
            "evidence_items": [e.to_dict() for e in self.evidence_items],
            "hidden_state": self.hidden_state,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HopScore:
        return cls(
            trace_id=data.get("trace_id", 0),
            session_id=data.get("session_id", ""),
            sender_did=data.get("sender_did", ""),
            field_type=data.get("field_type", ""),
            hop_count=data.get("hop_count", [0, 0]),
            score=data.get("score", 0.0),
            dimensions=data.get("dimensions", []),
            breadth=data.get("breadth", 0),
            severity=data.get("severity", "none"),
            deviation_type=data.get("deviation_type", "none"),
            evidence_items=[EvidenceItem.from_dict(e) for e in data.get("evidence_items", [])],
            hidden_state=data.get("hidden_state", ""),
            timestamp=data.get("timestamp", 0.0),
        )


# ======================================================================
# EvidenceItem — 纵横共用
# ======================================================================

@dataclass
class EvidenceItem:
    """A single piece of evidence referencing specific trace entries."""

    description: str
    trace_ids: list[int] = field(default_factory=list)
    field_type: str = ""
    severity_hint: str = "info"  # info / warning / critical

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "trace_ids": self.trace_ids,
            "field_type": self.field_type,
            "severity_hint": self.severity_hint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvidenceItem:
        return cls(
            description=data.get("description", ""),
            trace_ids=data.get("trace_ids", []),
            field_type=data.get("field_type", ""),
            severity_hint=data.get("severity_hint", "info"),
        )
