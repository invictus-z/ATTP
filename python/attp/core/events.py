"""ATTP 进程内事件总线 — 协议节点 SSE 推送的基础。

为协议节点的 trace/analysis/malicious 写入点提供发布-订阅能力，
由 SSE 端点（``/api/events``）订阅并推送给用户端。

设计要点：
- 单进程、单实例；非分布式（多协议节点实例间不共享事件）。
- 每订阅者一个有界 ``asyncio.Queue``，溢出丢最旧并计数（防慢客户端撑爆内存）。
- 支持 topic / session_id / did 过滤，避免无关事件入队。
- None-safe：组件持有 ``broker: EventBroker | None``，未注入时跳过发布。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from attp.app.logging import get_logger

logger = get_logger("EventBroker")

#: 单个订阅者队列的最大容量，溢出时丢弃最旧事件。
QUEUE_MAXSIZE = 256


@dataclass
class Event:
    """一条待推送的事件。"""

    id: int
    type: str
    topic: str
    payload: dict[str, Any]


@dataclass
class Subscription:
    """一个 SSE 客户端订阅。"""

    id: int
    queue: asyncio.Queue[Event]
    topics: set[str] | None = None
    session_id: str | None = None
    did: str | None = None
    dropped: int = 0

    def matches(self, event: Event) -> bool:
        """事件是否匹配本订阅的过滤条件。"""
        if self.topics is not None and event.topic not in self.topics:
            return False
        if self.session_id is not None:
            if event.payload.get("session_id") != self.session_id:
                return False
        if self.did is not None:
            did_val = event.payload.get("did") or event.payload.get("target_did") or ""
            if did_val != self.did:
                return False
        return True


class EventBroker:
    """进程内事件总线：发布者广播，订阅者按过滤条件接收。"""

    def __init__(self) -> None:
        self._subs: dict[int, Subscription] = {}
        self._next_sub_id = 0
        self._next_event_id = 0

    async def publish(
        self, event_type: str, payload: dict[str, Any], *, topic: str
    ) -> None:
        """发布一条事件到所有匹配的订阅者。

        队列满时丢弃最旧事件以容纳最新事件（慢客户端保护）。
        """
        self._next_event_id += 1
        event = Event(id=self._next_event_id, type=event_type, topic=topic, payload=payload)
        for sub in self._subs.values():
            if not sub.matches(event):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                # 丢最旧，腾出空间给最新
                try:
                    sub.queue.get_nowait()
                    sub.dropped += 1
                    sub.queue.put_nowait(event)
                    logger.warning(
                        "EventBroker: subscription {} queue full, dropped oldest "
                        "(total dropped={})",
                        sub.id, sub.dropped,
                    )
                except asyncio.QueueEmpty:
                    pass
                except asyncio.QueueFull:
                    logger.warning(
                        "EventBroker: subscription {} queue still full after drop, "
                        "event {} lost",
                        sub.id, event.type,
                    )

    def subscribe(
        self,
        topics: set[str] | None = None,
        session_id: str | None = None,
        did: str | None = None,
    ) -> Subscription:
        """创建一个订阅。返回的 Subscription 可用于迭代事件队列。"""
        self._next_sub_id += 1
        sub = Subscription(
            id=self._next_sub_id,
            queue=asyncio.Queue(maxsize=QUEUE_MAXSIZE),
            topics=set(topics) if topics else None,
            session_id=session_id,
            did=did,
        )
        self._subs[sub.id] = sub
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        """取消订阅。"""
        self._subs.pop(sub.id, None)
