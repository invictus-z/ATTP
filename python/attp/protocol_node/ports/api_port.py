"""端口二：API 服务端 — 协议相关的 REST API 接口。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("ApiPort")

if TYPE_CHECKING:
    from attp.core.pn_tracer import ProtocolTracer
    from attp.core.sessions.protocol_node import ProtocolSessionManager


class ApiPort:
    """Protocol Node 端口二：行为溯源 + 分析报告 + 污点审计 API。"""

    def __init__(
        self,
        tracer: ProtocolTracer,
        session_manager: ProtocolSessionManager,
        host: str,
        port: int,
    ):
        self._tracer = tracer
        self._session_manager = session_manager
        self.host = host
        self.port = port
        self._app = FastAPI(title="ATTP Protocol Node — API Port")
        self._orchestrator = None
        self._uvicorn_server = None
        self._serve_task = None

    def set_orchestrator(self, orchestrator) -> None:
        """注入 AnalysisOrchestrator 并挂载路由。"""
        self._orchestrator = orchestrator
        self._mount_routes()

    def _mount_routes(self) -> None:
        """挂载协议相关 API 路由。"""
        from attp.protocol_node.api.trace import get_behavior_router
        from attp.protocol_node.api.malicious import get_malicious_router
        self._app.include_router(
            get_behavior_router(
                tracer=self._tracer,
                session_manager=self._session_manager,
                orchestrator=self._orchestrator,
            )
        )
        self._app.include_router(get_malicious_router(tracer=self._tracer))

    async def start(self) -> None:
        """启动 API Port uvicorn 服务。"""
        # 确保路由已挂载
        if not self._orchestrator:
            self._mount_routes()

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
        """停止 API Port。"""
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
