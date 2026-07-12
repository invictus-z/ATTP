"""统一端口 — 合并原 DataPort（/record）+ ApiPort（/api/*）+ SSE（/api/events）。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("ProtocolPort")

if TYPE_CHECKING:
    from attp.core.sse import EventBroker
    from attp.core.pn_tracer import ProtocolTracer
    from attp.core.sessions.protocol_node import ProtocolSessionManager


class ProtocolPort:
    """Protocol Node 统一端口：record 接收 + API 查询。

    路由：
        POST /record                    — 接收并处理 record 消息
        GET  /api/status                — 健康检查
        GET  /api/behavior/{session_id} — 行为溯源
        GET  /api/analysis/{session_id} — 分析报告
        GET  /api/malicious/...         — 恶意节点查询
        ...其他 API 路由
    """

    def __init__(
        self,
        tracer: ProtocolTracer,
        session_manager: ProtocolSessionManager,
        host: str,
        port: int,
        did_resolver,
        behavior_controller,
        malicious_detector,
        event_broker: EventBroker | None = None,
    ):
        self._tracer = tracer
        self._session_manager = session_manager
        self.host = host
        self.port = port
        self._did_resolver = did_resolver
        self._behavior_controller = behavior_controller
        self._malicious_detector = malicious_detector
        self._broker = event_broker

        self._app = FastAPI(title="ATTP Protocol Node")
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self._orchestrator = None
        self._orch_holder: list = [None]  # mutable list for late-binding
        self._uvicorn_server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task | None = None

        # 挂载路由
        self._mount_routes()

    def _mount_routes(self) -> None:
        """挂载所有路由：/record + /api/*。"""
        # 1. /record 路由
        from attp.protocol_node.api.record import get_record_router

        self._app.include_router(
            get_record_router(
                tracer=self._tracer,
                session_manager=self._session_manager,
                did_resolver=self._did_resolver,
                behavior_controller=self._behavior_controller,
                malicious_detector=self._malicious_detector,
                orchestrator_holder=self._orch_holder,
                event_broker=self._broker,
            )
        )

        # 2. /api/* 路由 — 行为溯源
        from attp.protocol_node.api.trace import get_behavior_router
        from attp.protocol_node.api.malicious import get_malicious_router

        self._app.include_router(
            get_behavior_router(tracer=self._tracer)
        )
        self._app.include_router(
            get_malicious_router(tracer=self._tracer)
        )

        # 3. Cross-Lock 分析路由（纵向 + 横向 + 综合视图）
        from attp.protocol_node.api.analysis.vertical import get_vertical_analysis_router
        from attp.protocol_node.api.analysis.horizontal import get_horizontal_analysis_router
        from attp.protocol_node.api.analysis.cross_lock import get_cross_lock_router

        self._app.include_router(
            get_vertical_analysis_router(
                tracer=self._tracer,
                session_manager=self._session_manager,
                coordinator_holder=self._orch_holder,
            )
        )
        self._app.include_router(
            get_horizontal_analysis_router(
                tracer=self._tracer,
                coordinator_holder=self._orch_holder,
            )
        )
        self._app.include_router(
            get_cross_lock_router(tracer=self._tracer)
        )

        # 4. SSE 事件流路由
        if self._broker is not None:
            from attp.protocol_node.api.events import get_events_router

            self._app.include_router(get_events_router(self._broker))

    def set_orchestrator(self, orchestrator) -> None:
        """注入 CrossLockCoordinator 并更新所有路由引用。"""
        self._orchestrator = orchestrator
        self._orch_holder[0] = orchestrator

    async def start(self) -> None:
        """启动统一端口 uvicorn 服务。"""
        cfg = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
            log_config=UVICORN_SILENT_LOG_CONFIG,
        )
        self._uvicorn_server = uvicorn.Server(cfg)
        self._serve_task = asyncio.create_task(self._uvicorn_server.serve())
        logger.info("started at {}:{}", self.host, self.port)

    async def stop(self) -> None:
        """停止服务。"""
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass