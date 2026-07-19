"""Cross-Lock Intent Tracking — 十字锁定意图追踪架构（逐跳改版）。

纵轴 (VerticalAxis):  per-session 逐跳 V-Reasoner 评分（意图流 + 4 维 + R_T）
横轴 (HorizontalAxis): per-DID F 累加（跨会话叠加）+ α 会话确认
"""

from attp.core.analysis.base_models import (
    DIMENSION_NAMES,
    EvidenceItem,
    HopScore,
    IntentRevision,
    IntentRevisionSource,
    aggregate_score,
    compute_breadth,
    overall_verdict_for_severities,
    severity_for_score,
)

from attp.core.analysis.vertical.models import VerticalSessionReport
from attp.core.analysis.vertical.analyzer import VerticalIntentAnalyzer
from attp.core.analysis.vertical.orchestrator import VerticalOrchestrator

from attp.core.analysis.horizontal.models import (
    ConfirmationReport,
    ConfirmationVerdict,
    CrossSessionProfile,
)
from attp.core.analysis.horizontal.analyzer import HorizontalIntentAnalyzer
from attp.core.analysis.horizontal.orchestrator import HorizontalOrchestrator

from attp.core.analysis.cross_lock import CrossLockCoordinator

__all__ = [
    # base
    "DIMENSION_NAMES",
    "EvidenceItem",
    "HopScore",
    "IntentRevision",
    "IntentRevisionSource",
    "aggregate_score",
    "compute_breadth",
    "overall_verdict_for_severities",
    "severity_for_score",
    # vertical
    "VerticalSessionReport",
    "VerticalIntentAnalyzer",
    "VerticalOrchestrator",
    # horizontal
    "CrossSessionProfile",
    "ConfirmationVerdict",
    "ConfirmationReport",
    "HorizontalIntentAnalyzer",
    "HorizontalOrchestrator",
    # coordinator
    "CrossLockCoordinator",
]
