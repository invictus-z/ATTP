from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, TYPE_CHECKING

from attp.app.logging import get_logger

logger = get_logger("Channel")

from pydantic import Field

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base

from attp.app.client import ATTPClient
from attp.app.server import ATTPServer
from attp.app.config import ConfigManager
from attp.app.heartbeat import HeartbeatManager
from attp.app.web import WebApp
from attp.core.sessions import SessionManager
from attp.app.tools import SendMessageTool
from attp.core.tracer import MessageTracer

if TYPE_CHECKING:
    from attp.app.config.config import ATTPConfigFile


class ATTPConfig(Base):
    """ATTP channel configuration."""
    enabled: bool = False
    config_path: str = "~/.nanobot/attp_config.json"
    allow_from: list[str] = Field(default_factory=lambda: ["*"])


class ATTPChannel(BaseChannel):
    name = "attp"
    display_name = "ATTP"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = ATTPConfig(**config)
        super().__init__(config, bus)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ATTPConfig().model_dump(by_alias=True)

    async def start(self) -> None:
        """
        启动 ATTP channel
        """
        self._running = True
        config_path = self.config.config_path

        # 构建ConfigManager
        self._config_manager = ConfigManager(config_path)
        self._attp_cfg = self._config_manager.attp_config

        # 构建Tracer
        storage_cfg = self._attp_cfg.storage
        tracer_db_path = str(Path(storage_cfg.data_dir).expanduser() / storage_cfg.db_path)
        self._tracer = await MessageTracer.create(db_path=tracer_db_path)

        # 构建后端服务器 web_app/
        self._web_app = WebApp(
            web_config=self._attp_cfg.web_app,
            channel_callback=self._receive,
            tracer=self._tracer,
        )

        # 构建SessionManager
        self._session_manager = SessionManager()

        # 构建所有组件
        self._attp_client = ATTPClient(
            agent_did=self._attp_cfg.did,
            client_config=self._attp_cfg.attp_client,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message,
            tracer=self._tracer,
        )
        self._attp_server = ATTPServer(
            agent_did=self._attp_cfg.did,
            server_config=self._attp_cfg.attp_server,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message,
            attp_channel_callback = self._receive,
        )
        self._heartbeat_manager = HeartbeatManager(
            heartbeat_config=self._attp_cfg.heartbeat,
            attp_client=self._attp_client,
        )
        self._send_message_tool = SendMessageTool(
            tool_config=self._attp_cfg.tool,
            callback=self._attp_client.send_message,
        )

        # ------------------------------------------------------------------
        # 混合模式：条件启动 ProtocolNode + AnalysisOrchestrator
        # Orchestrator 依赖 DataPort 的 /record 端点触发 on_record_received，
        # 因此仅在 ProtocolNode 启用时才构建。
        # ------------------------------------------------------------------
        self._protocol_node = None
        self._analysis_orchestrator = None
        pn_cfg = self._attp_cfg.protocol_node
        if pn_cfg.enabled:
            from attp.protocol_node import ProtocolNode

            self._protocol_node = ProtocolNode(
                data_port_host=pn_cfg.data_port_host,
                data_port_port=pn_cfg.data_port_port,
                api_port_host=pn_cfg.api_port_host,
                api_port_port=pn_cfg.api_port_port,
                tracer=self._tracer,
                session_manager=self._session_manager,
                agent_did=self._attp_cfg.did,
            )

            # 构建并注入 AnalysisOrchestrator
            self._analysis_orchestrator = self._build_analysis_orchestrator()
            if self._analysis_orchestrator:
                self._protocol_node.set_orchestrator(self._analysis_orchestrator)

            logger.info(
                "ProtocolNode enabled: data_port={}:{}, api_port={}:{}",
                pn_cfg.data_port_host, pn_cfg.data_port_port,
                pn_cfg.api_port_host, pn_cfg.api_port_port,
            )

        # 并发启动所有组件 启动阶段无依赖关系
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._attp_client.start())
            tg.create_task(self._attp_server.start())
            tg.create_task(self._heartbeat_manager.start())
            tg.create_task(self._send_message_tool.start())
            tg.create_task(self._web_app.start(
                self._attp_client, self._config_manager,
                reload_callback=self.reload,
                session_manager=self._session_manager,
                agent_did=self._attp_cfg.did,
            ))
            if self._protocol_node:
                tg.create_task(self._protocol_node.start())

        # start() must block forever (or until stop() is called).
        while self._running:
            await asyncio.sleep(1)

        # 并发停止所有组件
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_manager.stop())
            tg.create_task(self._send_message_tool.stop())
            tg.create_task(self._attp_client.stop())
            tg.create_task(self._attp_server.stop())
            tg.create_task(self._web_app.stop())
            if self._protocol_node:
                tg.create_task(self._protocol_node.stop())

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Send message back to UI via WebSocket (called by ChannelManager)."""
        msg.metadata["Session_ID"] = msg.chat_id
        await self._web_app.record_message(msg.content, msg.metadata)

    async def _receive(self, sender: str, chat_id: str, content: str, media: list[str]) -> str:
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=content,
            media=media,
        )
        return "ok"

    async def reload(self, old_cfg: ATTPConfigFile, new_cfg: ATTPConfigFile) -> None:
        """Hot-reload only the components whose config has changed.

        WebApp host/port changes are logged as warnings (requires manual restart).
        """
        # DID or ATTPClient config changed
        if old_cfg.did != new_cfg.did or old_cfg.attp_client.changed_fields(new_cfg.attp_client):
            logger.info("ATTPClient config changed, reloading...")
            await self._attp_client.reload(new_cfg.attp_client, new_cfg.did)

        # ATTPServer config changed (also triggers on DID change)
        if old_cfg.did != new_cfg.did or old_cfg.attp_server.changed_fields(new_cfg.attp_server):
            logger.info("ATTPServer config changed, reloading...")
            await self._attp_server.reload(new_cfg.attp_server, new_cfg.did)

        # Heartbeat config changed
        if old_cfg.heartbeat.changed_fields(new_cfg.heartbeat):
            logger.info("Heartbeat config changed, reloading...")
            await self._heartbeat_manager.reload(new_cfg.heartbeat)

        # Tool config changed
        if old_cfg.tool.changed_fields(new_cfg.tool):
            logger.info("SendMessageTool config changed, reloading...")
            await self._send_message_tool.reload(new_cfg.tool)

        # Analysis config changed — rebuild orchestrator（仅在 ProtocolNode 启用时生效）
        if old_cfg.analysis.changed_fields(new_cfg.analysis):
            if self._protocol_node:
                logger.info("Analysis config changed, rebuilding orchestrator...")
                self._analysis_orchestrator = self._build_analysis_orchestrator(new_cfg)
                if self._analysis_orchestrator:
                    self._protocol_node.set_orchestrator(self._analysis_orchestrator)
                else:
                    self._protocol_node.set_orchestrator(None)
                logger.info("Analyzer reloaded: enabled={}", new_cfg.analysis.enabled)
            else:
                logger.warning("Analysis config changed but ProtocolNode is not enabled — ignored")

        # ProtocolNode config changed
        if old_cfg.protocol_node.changed_fields(new_cfg.protocol_node):
            logger.warning(
                "ProtocolNode config changed — requires manual restart (old={}, new={})",
                old_cfg.protocol_node.model_dump(),
                new_cfg.protocol_node.model_dump(),
            )

        # WebApp config changed — cannot restart self, just update attributes
        if old_cfg.web_app.changed_fields(new_cfg.web_app):
            self._web_app.host = new_cfg.web_app.host
            self._web_app.port = new_cfg.web_app.port
            logger.warning(
                "WebApp host/port changed to {}:{} — requires manual restart",
                new_cfg.web_app.host, new_cfg.web_app.port,
            )

        self._attp_cfg = new_cfg
        logger.info("hot-reload complete")

    # ------------------------------------------------------------------
    # Analysis orchestrator factory
    # ------------------------------------------------------------------

    def _build_analysis_orchestrator(self, cfg: ATTPConfigFile | None = None):
        """Create an AnalysisOrchestrator from config, or return None if disabled."""
        cfg = cfg or self._attp_cfg
        analysis_cfg = cfg.analysis
        if not analysis_cfg.enabled or not analysis_cfg.api_key:
            return None

        from attp.core.analysis import SemanticTaintAnalyzer, AnalysisOrchestrator
        analyzer = SemanticTaintAnalyzer(
            api_key=analysis_cfg.api_key,
            base_url=analysis_cfg.base_url,
            model=analysis_cfg.model,
        )
        logger.info(
            "Semantic taint analysis enabled (model={}, batch_size={})",
            analysis_cfg.model, analysis_cfg.report_batch_size,
        )
        return AnalysisOrchestrator(
            analyzer=analyzer,
            session_manager=self._session_manager,
            tracer=self._tracer,
            batch_size=analysis_cfg.report_batch_size,
        )
