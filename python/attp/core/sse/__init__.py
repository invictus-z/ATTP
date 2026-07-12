"""ATTP SSE 子系统 — 进程内事件总线 + SSE 帧序列化 + 事件词汇表。

公共出口：
- :class:`EventBroker` / :class:`Event` / :class:`Subscription` —— 发布-订阅总线（broker）
- :func:`format_event_frame` / :data:`HEARTBEAT` —— SSE 帧序列化（frames）
- :class:`Topic` / :class:`EventType` —— 事件常量（schema）

架构边界：本包**不依赖任何 web 框架**（纯 asyncio + 标准库），故可安全置于
``core/``。SSE 的 HTTP 接线（FastAPI ``StreamingResponse`` + 心跳循环）在 web 层
（``attp.protocol_node.api.events``），仅作为本包的薄适配。
"""

from attp.core.sse.broker import Event, EventBroker, Subscription
from attp.core.sse.frames import HEARTBEAT, format_event_frame
from attp.core.sse.schema import EventType, Topic

__all__ = [
    "Event",
    "EventBroker",
    "Subscription",
    "HEARTBEAT",
    "format_event_frame",
    "EventType",
    "Topic",
]
