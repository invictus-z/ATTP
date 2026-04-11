""" MCP 工具(sse based) 用于向其他agent或用户转发消息"""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

import uvicorn
from mcp.server.fastmcp import FastMCP

from attp_channel.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("Tool")

from attp_channel.config.config import ToolConfig


class SendMessageTool:
    """MCP tool server that delegates message sending to a callback."""

    def __init__(self, tool_config: ToolConfig, callback: Callable[[str, str, str], Awaitable[str]]) -> None:
        """Initialise the tool server.

        Args:
            tool_config: Configuration for the tool.
            callback: An async function ``(target, content, chat_id) -> str``
                      that handles the actual message delivery logic.
        """
        self._callback = callback
        self.host = tool_config.host
        self.port = tool_config.port
        self._task: asyncio.Task | None = None

        # 使用 FastMCP 高级 API，自动处理 SSE 路由
        self._mcp = FastMCP("attp-send-message")

        # 通过闭包捕获 self._callback
        _cb = self._callback

        @self._mcp.tool(
            name="send_message_tool",
            description=(
                "必须且只能使用此工具来发送消息给主人或其他 Agent。"
                "绝对不允许尝试自己构造或使用 JSON-RPC 等不存在或未经定义的接口。"
                "如果你找不到工具，请回复 '我无法找到发送消息工具'。\n\n"
                "参数说明：\n"
                "- target: 目标地址。发给主人使用 \"user:web_ui\"；"
                "发给其他 agent 使用对应节点的完整 DID，"
                "例如 \"did:wba:home.local:furniture-manager\"\n"
                "- content: 消息内容\n"
                "- chat_id: 当前会话ID，用于路由和追踪"
            ),
        )
        async def send_message_tool(target: str, content: str, chat_id: str) -> str:
            if not target or not content or not chat_id:
                return "Error: target, content and chat_id are all required."
            try:
                result = await _cb(target, content, chat_id)
            except Exception as exc:
                logger.exception("send_message callback failed")
                result = f"Error: {exc}"
            return result if isinstance(result, str) else str(result)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the MCP SSE server in the background."""
        if self._task is not None and not self._task.done():
            logger.warning("already running")
            return

        # sse_app() 返回完整配置好的 Starlette 应用
        starlette_app = self._mcp.sse_app()

        config = uvicorn.Config(starlette_app, host=self.host, port=self.port, log_level="info", log_config=UVICORN_SILENT_LOG_CONFIG)
        server = uvicorn.Server(config)

        async def _run() -> None:
            await server.serve()

        self._task = asyncio.create_task(_run())
        self._uvicorn_server = server
        logger.info("started at {}:{}", self.host, self.port)

    async def stop(self) -> None:
        """Stop the MCP SSE server."""
        if self._task is None:
            return

        if hasattr(self, "_uvicorn_server") and self._uvicorn_server:
            self._uvicorn_server.should_exit = True

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("stopped")

    async def reload(self, tool_config: ToolConfig) -> None:
        """Stop → update host/port → restart. Callback remains unchanged."""
        await self.stop()
        self.host = tool_config.host
        self.port = tool_config.port
        await self.start()
        logger.info("reloaded on {}:{}", self.host, self.port)
