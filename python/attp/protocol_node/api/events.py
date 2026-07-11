"""协议节点 SSE 端点 — ``GET /api/events``。

向用户端推送 trace/analysis/malicious 实时事件，替代前端轮询。

事件帧格式（标准 SSE）::

    id: <单调递增 id>
    event: <analysis.progress | analysis.report | malicious.detected | trace.recorded>
    data: <JSON payload>

空闲时每 15 秒发送 ``: ping`` 心跳，防止反向代理关闭空闲连接。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from attp.app.logging import get_logger

if TYPE_CHECKING:
    from attp.core.events import EventBroker

logger = get_logger("SseApi")

#: 空闲心跳间隔（秒）。
HEARTBEAT_SECONDS = 15.0


def get_events_router(broker: "EventBroker") -> APIRouter:
    """返回 ``/api/events`` SSE 路由。"""
    router = APIRouter(prefix="/api")

    @router.get("/events")
    async def sse_endpoint(
        session_id: str | None = None,
        did: str | None = None,
        topics: str | None = None,
    ) -> StreamingResponse:
        """订阅事件流。

        查询参数：
            session_id: 仅接收该 session 的事件（trace / 纵向 analysis）。
            did: 仅接收该 DID 的事件（横向 analysis / malicious）。
            topics: 逗号分隔的 topic 列表，如 ``trace,analysis,malicious``。
        """
        topic_set = (
            {t.strip() for t in topics.split(",") if t.strip()} if topics else None
        )
        sub = broker.subscribe(topics=topic_set, session_id=session_id, did=did)

        async def event_stream():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(
                            sub.queue.get(), timeout=HEARTBEAT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    data = json.dumps(event.payload, ensure_ascii=False)
                    yield f"id: {event.id}\nevent: {event.type}\ndata: {data}\n\n"
            finally:
                broker.unsubscribe(sub)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router
