import asyncio
from typing import Any

from loguru import logger
from pydantic import Field

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base

from attp_channel.client import ATTPClient
from attp_channel.server import ATTPServer
from attp_channel.config import ConfigManager
from attp_channel.heartbeat import HeartbeatManager
from attp_channel.web_app import WebApp
from attp_channel.sessions import SessionManager
from attp_channel.tools import SendMessageTool


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
        return {"enabled": False, "config_path": "~/.nanobot/attp_config.json", "allowFrom": []}

    async def start(self) -> None:
        """
        启动 ATTP channel
        """
        self._running = True
        config_path = self.config.config_path

        # 启动ANPConfigManager
        self._config_manager = ConfigManager(config_path)
        self._config_manager.load()
        self._anp_cfg = self._config_manager.attp_config

        # 构建后端服务器 web_app/
        self._web_app = WebApp(
            web_config=self._anp_cfg.web_app,
            channel_callback=self._receive
        )

        # 启动SessionManager
        self._session_manager = SessionManager()

        # 启动ATTP client & server
        self._attp_client = ATTPClient(
            agent_did=self._anp_cfg.did,
            client_config=self._anp_cfg.attp_client,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message
        )
        await self._attp_client.start()

        self._attp_server = ATTPServer(
            agent_did=self._anp_cfg.did,    
            server_config=self._anp_cfg.attp_server,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message,
            attp_channel_callback = self._receive
        )
        await self._attp_server.start()

        # 启动心跳管理器
        self._heartbeat_manager = HeartbeatManager(
            heartbeat_config=self._anp_cfg.heartbeat,
            attp_client=self._attp_client,
        )
        self._heartbeat_manager.start()

        # 启动 MCP 工具
        self._send_message_tool = SendMessageTool(
            tool_config=self._anp_cfg.tool,
            callback = self._attp_client.send_message
        )
        await self._send_message_tool.start()

        await self._web_app.start(self._attp_client, self._config_manager)

        # start() must block forever (or until stop() is called).
        while self._running:
            await asyncio.sleep(1)

        await self._heartbeat_manager.stop()
        await self._send_message_tool.stop()
        await self._attp_client.stop()
        await self._attp_server.stop()
        await self._web_app.stop()

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Send message back to UI via WebSocket (called by ChannelManager)."""
        await self._web_app.record_message(msg.content, msg.metadata)

    async def _receive(self, sender: str, chat_id: str, content: str, media: list[str]) -> str:
        print(sender, chat_id, content, media)
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=content,
            media=media,
        )
        return "ok"
