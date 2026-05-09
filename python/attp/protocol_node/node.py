"""ProtocolNode — 协议节点主类，管理双端口生命周期。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from attp.app.logging import get_logger
from attp.core.sessions import SessionManager
from attp.core.tracer import MessageTracer

if TYPE_CHECKING:
    from attp.core.analysis.orchestrator import AnalysisOrchestrator

logger = get_logger("ProtocolNode")


class ProtocolNode:
    """协议节点：封装 DataPort（端口一）+ ApiPort（端口二）。"""

    def __init__(
        self,
        data_port_host: str,
        data_port_port: int,
        api_port_host: str,
        api_port_port: int,
        tracer: MessageTracer,
        session_manager: SessionManager,
        agent_did: str = "",
    ):
        from attp.protocol_node.data_port import DataPort
        from attp.protocol_node.api_port import ApiPort

        self._tracer = tracer
        self._session_manager = session_manager
        self._agent_did = agent_did

        self._data_port = DataPort(
            tracer=tracer,
            session_manager=session_manager,
            agent_did=agent_did,
            host=data_port_host,
            port=data_port_port,
        )
        self._api_port = ApiPort(
            tracer=tracer,
            session_manager=session_manager,
            host=api_port_host,
            port=api_port_port,
        )

    def set_orchestrator(self, orchestrator: AnalysisOrchestrator) -> None:
        """注入 AnalysisOrchestrator 到双端口。"""
        self._data_port.set_orchestrator(orchestrator)
        self._api_port.set_orchestrator(orchestrator)
        logger.info("AnalysisOrchestrator injected into ProtocolNode")

    async def start(self) -> None:
        """并发启动双端口服务。"""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._data_port.start())
            tg.create_task(self._api_port.start())
        logger.info("ProtocolNode started (data={}, api={})",
                     self._data_port.port, self._api_port.port)

    async def stop(self) -> None:
        """并发停止双端口服务。"""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._data_port.stop())
            tg.create_task(self._api_port.stop())
        logger.info("ProtocolNode stopped")
