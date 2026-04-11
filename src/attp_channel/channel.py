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
        return ATTPConfig().model_dump(by_alias=True)

    async def start(self) -> None:
        """
        启动 ATTP channel
        """
        self._running = True
        config_path = self.config.config_path

        # 构建ConfigManager
        self._config_manager = ConfigManager(config_path)
        self._config_manager.load()
        self._anp_cfg = self._config_manager.attp_config

        # 构建后端服务器 web_app/
        self._web_app = WebApp(
            web_config=self._anp_cfg.web_app,
            channel_callback=self._receive
        )

        # 构建SessionManager
        self._session_manager = SessionManager()

        # 构建所有组件
        self._attp_client = ATTPClient(
            agent_did=self._anp_cfg.did,
            client_config=self._anp_cfg.attp_client,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message
        )
        self._attp_server = ATTPServer(
            agent_did=self._anp_cfg.did,    
            server_config=self._anp_cfg.attp_server,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message,
            attp_channel_callback = self._receive
        )
        self._heartbeat_manager = HeartbeatManager(
            heartbeat_config=self._anp_cfg.heartbeat,
            attp_client=self._attp_client,
        )
        self._send_message_tool = SendMessageTool(
            tool_config=self._anp_cfg.tool,
            callback = self._attp_client.send_message
        )

        # 并发启动所有组件 启动阶段无依赖关系
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._attp_client.start())
            tg.create_task(self._attp_server.start())
            tg.create_task(self._heartbeat_manager.start())
            tg.create_task(self._send_message_tool.start())
            tg.create_task(self._web_app.start(self._attp_client, self._config_manager))

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
