"""Analysis API — 十字锁定（Cross-Lock）分析路由包。

- vertical:   /api/analysis/v/...   (Session 级纵向语义意图追踪)
- horizontal: /api/analysis/h/...   (DID 级横向全局行为分析)
- cross_lock: /api/analysis/cross-lock/{session_id}  (综合视图)
"""

from .vertical import get_vertical_analysis_router
from .horizontal import get_horizontal_analysis_router
from .cross_lock import get_cross_lock_router

__all__ = [
    "get_vertical_analysis_router",
    "get_horizontal_analysis_router",
    "get_cross_lock_router",
]
