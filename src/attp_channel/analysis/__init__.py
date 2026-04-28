"""Semantic taint analysis — LLM-based post-penetration behavior detection."""

from .analyzer import SemanticTaintAnalyzer
from .models import (
    IntentDescriptor,
    NodeBehaviorProfile,
    NodeTaintVerdict,
    TaintReport,
)

__all__ = [
    "SemanticTaintAnalyzer",
    "IntentDescriptor",
    "NodeBehaviorProfile",
    "NodeTaintVerdict",
    "TaintReport",
]
