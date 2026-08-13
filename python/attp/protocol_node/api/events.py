"""协议节点 SSE 端点 — ``GET /api/events``（FastAPI 适配层）。

向用户端推送 trace/analysis/malicious/record 实时事件，替代前端轮询。

本模块只负责 **HTTP 接线**（``StreamingResponse`` + 心跳循环）；事件总线与
SSE 帧序列化在 ``attp.core.sse``，从而保持 ``core/`` 框架无关、SSE 机理集中。

事件帧格式（标准 SSE）::

    id: <单调递增 id>
    event: <analysis.progress | analysis.report | malicious.detected | trace.recorded | ...>
    data: <JSON payload>

空闲时每 ``HEARTBEAT_SECONDS`` 秒发送 ``: ping`` 心跳，防止反向代理关闭空闲连接。

查询参数：
    session_id: 仅接收该 session 的事件（trace / 纵向 analysis）。
    did:        仅接收该 DID 的事件（横向 analysis / malicious）。
    topics:     逗号分隔的 topic 列表，如 ``trace,analysis,malicious``。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from attp.app.logging import get_logger
from attp.core.sse import EventBroker, HEARTBEAT, format_event_frame

logger = get_logger("SseApi")

#: 空闲心跳间隔（秒）。
HEARTBEAT_SECONDS = 15.0


def get_events_router(broker: EventBroker) -> APIRouter:
    """返回 ``/api/events`` SSE 路由。"""
    router = APIRouter(prefix="/api")

    @router.get("/events")
    async def sse_endpoint(
        session_id: str | None = None,
        did: str | None = None,
        topics: str | None = None,
    ) -> StreamingResponse:
        """订阅事件流。"""
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
                        yield HEARTBEAT
                        continue
                    yield format_event_frame(event.id, event.type, event.payload)
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
