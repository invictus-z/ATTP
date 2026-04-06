""" MCP 工具(sse based) 用于向其他agent或用户转发消息"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Awaitable

import uvicorn
from loguru import logger
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.routing import Route

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

        self._app = Server("attp-send-message")
        self._task: asyncio.Task | None = None

        self._app.list_tools()(self._list_tools)
        self._app.call_tool()(self._call_tool)

    # ------------------------------------------------------------------
    # MCP handlers
    # ------------------------------------------------------------------

    async def _list_tools(self) -> list[Tool]:
        return [
            Tool(
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
                inputSchema={
                    "type": "object",
                    "properties": {
                        "target": {
                            "type": "string",
                            "description": (
                                "目标地址：'user:web_ui' 发给主人，"
                                "'did:wba:...' 发给其他 Agent"
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": "消息内容",
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "会话 ID，用于路由和追踪",
                        },
                    },
                    "required": ["target", "content", "chat_id"],
                },
            )
        ]

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name != "send_message_tool":
            return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

        target: str = arguments.get("target", "")
        content: str = arguments.get("content", "")
        chat_id: str = arguments.get("chat_id", "")

        if not target or not content or not chat_id:
            return [
                TextContent(
                    type="text",
                    text="Error: target, content and chat_id are all required.",
                )
            ]

        try:
            result = await self._callback(target, content, chat_id)
        except Exception as exc:
            logger.exception("send_message callback failed")
            result = f"Error: {exc}"

        return [TextContent(type="text", text=result if isinstance(result, str) else str(result))]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the MCP SSE server in the background."""
        if self._task is not None and not self._task.done():
            logger.warning("SendMessageTool is already running")
            return

        sse_transport = SseServerTransport("/messages")
        _mcp_app = self._app

        async def handle_sse(scope, receive, send):
            async with sse_transport.connect_sse(scope, receive, send) as streams:
                await _mcp_app.run(
                    streams[0],
                    streams[1],
                    _mcp_app.create_initialization_options(),
                )

        async def handle_post_message(scope, receive, send):
            await sse_transport.handle_post_message(scope, receive, send)

        starlette_app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Route("/messages", endpoint=handle_post_message, methods=["POST"]),
            ],
        )

        config = uvicorn.Config(starlette_app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)

        async def _run() -> None:
            await server.serve()

        self._task = asyncio.create_task(_run())
        self._uvicorn_server = server
        logger.info("SendMessageTool started on %s:%d", self.host, self.port)

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
        logger.info("SendMessageTool stopped")
