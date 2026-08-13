"""SSE 帧序列化 — 纯字符串处理，不依赖任何 web 框架。

将 :class:`~attp.core.sse.broker.Event` 序列化为标准 Server-Sent Events 帧，
供 web 层（FastAPI ``StreamingResponse`` 等）直接 yield。把"字节格式"集中在
core 层，使 ``core/`` 保持框架无关，同时 SSE 机理不散落到各处。
"""

from __future__ import annotations

import json
from typing import Any

#: 空闲心跳帧（SSE 注释行，以 ``:`` 开头，不触发浏览器 EventSource 事件）。
#: 用于防止反向代理关闭空闲连接。
HEARTBEAT = ": ping\n\n"


def format_event_frame(event_id: int, event_type: str, payload: dict[str, Any]) -> str:
    """将一条事件序列化为标准 SSE 帧。

    输出格式::

        id: <单调递增 id>
        event: <事件类型>
        data: <JSON payload>

    末尾空行标志一帧结束（SSE 协议要求）。
    """
    data = json.dumps(payload, ensure_ascii=False)
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
