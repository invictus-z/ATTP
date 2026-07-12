"""Cross-Lock Intent Tracking — 十字锁定意图追踪架构。

纵轴 (VerticalAxis):  Session-Level 实时语义意图追踪
横轴 (HorizontalAxis): Cross-Session / DID-Level 全局行为分析
"""

from attp.core.analysis.base_models import EvidenceItem, IntentDescriptor

from attp.core.analysis.vertical.models import (
    NodeBehaviorProfile,
    NodeIntentVerdict,
    VerticalIntentReport,
)
from attp.core.analysis.vertical.analyzer import VerticalIntentAnalyzer
from attp.core.analysis.vertical.orchestrator import VerticalOrchestrator

from attp.core.analysis.horizontal.models import (
    CrossSessionProfile,
    DIDVerdict,
    HorizontalIntentReport,
)
from attp.core.analysis.horizontal.analyzer import HorizontalIntentAnalyzer
from attp.core.analysis.horizontal.orchestrator import HorizontalOrchestrator

from attp.core.analysis.cross_lock import CrossLockCoordinator

__all__ = [
    "EvidenceItem",
    "IntentDescriptor",
    "VerticalIntentAnalyzer",
    "VerticalOrchestrator",
    "VerticalIntentReport",
    "NodeBehaviorProfile",
    "NodeIntentVerdict",
    "HorizontalIntentAnalyzer",
    "HorizontalOrchestrator",
    "HorizontalIntentReport",
    "CrossSessionProfile",
    "DIDVerdict",
    "CrossLockCoordinator",
]
