"""Vertical Axis — 纵向分析数据模型（逐跳改版）。

逐跳评分结果用共享的 ``HopScore``（base_models）；本模块提供会话级聚合视图
``VerticalSessionReport``，供 /report、/aggregate 等只读端点使用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VerticalSessionReport:
    """单会话的逐跳评分聚合视图（只读端点用）。

    overall_verdict 由代码按各跳 severity 推导（任跳 critical→malicious、任跳 high→suspicious）。
    """

    session_id: str
    initiator_did: str = ""
    intent_revisions: list[dict[str, Any]] = field(default_factory=list)
    hidden_state: str = ""
    hop_scores: list[dict[str, Any]] = field(default_factory=list)
    overall_verdict: str = "clean"  # clean / suspicious / malicious
    max_score: float = 0.0
    total_hops: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "initiator_did": self.initiator_did,
            "intent_revisions": self.intent_revisions,
            "hidden_state": self.hidden_state,
            "hop_scores": self.hop_scores,
            "overall_verdict": self.overall_verdict,
            "max_score": self.max_score,
            "total_hops": self.total_hops,
            "timestamp": self.timestamp,
        }
