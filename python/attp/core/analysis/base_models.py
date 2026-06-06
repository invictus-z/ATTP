"""Cross-Lock Taint Analysis — 共享基础数据模型。

纵横两轴共用的基础类型：IntentDescriptor（纵向专用）、EvidenceItem（纵横共用）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ======================================================================
# IntentDescriptor — 纵向分析专用（横向分析不需要用户意图）
# ======================================================================

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
