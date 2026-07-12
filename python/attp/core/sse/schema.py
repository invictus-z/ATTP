"""SSE 事件词汇表 — topic / event-type 常量。

集中定义所有发布到 :class:`~attp.core.sse.broker.EventBroker` 的事件标识，
消除散落在各发布点的魔法字符串，便于改名、查重与 IDE 跳转。

约定：
- ``Topic`` 为粗粒度分类，订阅者按此过滤（``GET /api/events?topics=...``）。
- ``EventType`` 为细粒度事件名，格式通常为 ``<scope>.<name>``。
  注意：type 的前缀**不必**与 topic 一致 —— 例如 ``horizontal.accumulated``
  归入 ``analysis`` topic，以便 ``topics=analysis`` 订阅一并接收。
- 过滤键：``session_id`` 直接匹配；``did`` 匹配 payload 的 ``did`` 或 ``target_did``。
"""

from __future__ import annotations


class Topic:
    """事件 topic（订阅者按此粗粒度过滤）。"""

    TRACE = "trace"
    ANALYSIS = "analysis"
    MALICIOUS = "malicious"
    RECORD = "record"


class EventType:
    """事件 type（细粒度事件名）。"""

    # ── trace ──
    TRACE_RECORDED = "trace.recorded"

    # ── analysis ──
    ANALYSIS_PROGRESS = "analysis.progress"
    ANALYSIS_REPORT = "analysis.report"
    HORIZONTAL_ACCUMULATED = "horizontal.accumulated"

    # ── malicious ──
    MALICIOUS_DETECTED = "malicious.detected"

    # ── record ──
    RECORD_ERROR = "record.error"
