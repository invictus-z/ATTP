"""Cross-Lock Taint Analysis — 十字锁定污点分析架构。

纵轴 (VerticalAxis):  Session-Level 实时语义污点分析
横轴 (HorizontalAxis): Cross-Session / DID-Level 全局行为分析
"""

from attp.core.analysis.base_models import EvidenceItem, IntentDescriptor

from attp.core.analysis.vertical.models import (
    NodeBehaviorProfile,
    NodeTaintVerdict,
    VerticalTaintReport,
)
from attp.core.analysis.vertical.analyzer import VerticalTaintAnalyzer
from attp.core.analysis.vertical.orchestrator import VerticalOrchestrator

from attp.core.analysis.horizontal.models import (
    CrossSessionProfile,
    DIDVerdict,
    HorizontalTaintReport,
)
from attp.core.analysis.horizontal.analyzer import HorizontalTaintAnalyzer
from attp.core.analysis.horizontal.orchestrator import HorizontalOrchestrator

from attp.core.analysis.cross_lock import CrossLockCoordinator

__all__ = [
    "EvidenceItem",
    "IntentDescriptor",
    "VerticalTaintAnalyzer",
    "VerticalOrchestrator",
    "VerticalTaintReport",
    "NodeBehaviorProfile",
    "NodeTaintVerdict",
    "HorizontalTaintAnalyzer",
    "HorizontalOrchestrator",
    "HorizontalTaintReport",
    "CrossSessionProfile",
    "DIDVerdict",
    "CrossLockCoordinator",
]
