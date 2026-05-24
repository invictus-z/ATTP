from __future__ import annotations

import asyncio
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
from attp.app.heartbeat import HeartbeatManager, AgentHealthChecker, ToolNodeHealthChecker
from attp.app.web import WebApp
from attp.core.sessions.app import AppSessionManager
from attp.app.tools import MCPToolBridge
from attp.core.agent_tracer import AgentTracer

if TYPE_CHECKING:
    from attp.app.config.config import ATTPConfigFile

from attp.app.logging import set_log_level
set_log_level("DEBUG")

class ATTPConfig(Base):
    """ATTP channel configuration."""
    enabled: bool = False
    config_path: str = "~/.attp/agent/nanobot/config.json"
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

        # 构建 AgentTracer（Agent 侧：轻量，无数据库）
        self._agent_tracer = AgentTracer()

        # 构建后端服务器 web_app/
        self._web_app = WebApp(
            web_config=self._attp_cfg.web_app,
            channel_callback=self._receive,
        )

        # 构建SessionManager
        self._app_session_manager = AppSessionManager()

        # 构建所有组件
        self._attp_client = ATTPClient(
            agent_did=self._attp_cfg.did,
            client_config=self._attp_cfg.attp_client,
            session_manager=self._app_session_manager,
            web_callback=self._web_app.record_message,
            tracer=self._agent_tracer,
        )
        self._attp_server = ATTPServer(
            agent_did=self._attp_cfg.did,
            server_config=self._attp_cfg.attp_server,
            session_manager=self._app_session_manager,
            web_callback=self._web_app.record_message,
            attp_channel_callback=self._receive,
            tracer=self._agent_tracer,
        )
        self._heartbeat_manager = HeartbeatManager(self._attp_cfg.heartbeat)
        self._heartbeat_manager.add_checker(AgentHealthChecker(
            attp_client=self._attp_client,
            timeout=self._attp_cfg.heartbeat.timeout,
            max_fail=self._attp_cfg.heartbeat.max_fail,
        ))
        self._tool_bridge = MCPToolBridge(
            tool_config=self._attp_cfg.tool,
            attp_client=self._attp_client,
            tracer=self._agent_tracer,
            session_manager=self._app_session_manager,
            agent_did=self._attp_cfg.did,
            send_callback=self._attp_client.send_message,
        )
        self._heartbeat_manager.add_checker(ToolNodeHealthChecker(
            tool_bridge=self._tool_bridge,
            timeout=self._attp_cfg.heartbeat.timeout,
            max_fail=self._attp_cfg.heartbeat.max_fail,
        ))

        # ------------------------------------------------------------------
        # 条件启动 ProtocolNode（自包含：传入 config_path 即可）
        # ------------------------------------------------------------------
        self._protocol_node = None
        pn_cfg = self._attp_cfg.protocol_node
        if pn_cfg.enabled:
            from attp.protocol_node import ProtocolNode

            self._protocol_node = ProtocolNode(
                config_path=pn_cfg.config_path,
            )
            logger.info("ProtocolNode enabled, config_path={}", pn_cfg.config_path)

        # 启动前自动发现工具节点
        tool_node_ads = self._attp_cfg.tool.tool_node_ads
        if tool_node_ads:
            await self._tool_bridge.discover_all_tool_nodes(tool_node_ads)

        # 并发启动所有组件 启动阶段无依赖关系
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._attp_client.start())
            tg.create_task(self._attp_server.start())
            tg.create_task(self._heartbeat_manager.start())
            tg.create_task(self._tool_bridge.start())
            tg.create_task(self._web_app.start(
                self._attp_client, self._config_manager,
                reload_callback=self.reload,
                session_manager=self._app_session_manager,
                agent_did=self._attp_cfg.did,
                tracer=self._agent_tracer,
                private_key_path=str(self._attp_client.auth.private_key_path),
            ))
            if self._protocol_node:
                tg.create_task(self._protocol_node.start())

        # start() must block forever (or until stop() is called).
        while self._running:
            await asyncio.sleep(1)

        # 并发停止所有组件
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_manager.stop())
            tg.create_task(self._tool_bridge.stop())
            tg.create_task(self._attp_client.stop())
            tg.create_task(self._attp_server.stop())
            tg.create_task(self._web_app.stop())
            if self._protocol_node:
                tg.create_task(self._protocol_node.stop())

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Send message back to UI via WebSocket (called by ChannelManager).

        所有 A2U NodeMessage 构建和回传逻辑由 WebApp.send_message_to_user 内部处理。
        """
        await self._web_app.send_message_to_user(msg.content, msg.chat_id)

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
            logger.info("ToolBridge config changed, reloading...")
            await self._tool_bridge.reload(new_cfg.tool)
            # 如果 tool_node_ads 变化，重新发现
            if old_cfg.tool.tool_node_ads != new_cfg.tool.tool_node_ads:
                for did in list(self._tool_bridge.get_tool_nodes()):
                    await self._tool_bridge.unregister_tool_node(did)
                if new_cfg.tool.tool_node_ads:
                    await self._tool_bridge.discover_all_tool_nodes(new_cfg.tool.tool_node_ads)

        # ProtocolNode config changed — 重新加载外部配置文件
        if old_cfg.protocol_node.changed_fields(new_cfg.protocol_node):
            if self._protocol_node:
                await self._protocol_node.reload_config()
            else:
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