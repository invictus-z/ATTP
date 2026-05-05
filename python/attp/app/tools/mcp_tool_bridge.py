"""MCPToolBridge — Agent 侧工具桥接器。

同时充当：
1. MCP SSE Server — 暴露给 nanobot（Agent 内置 MCP Client）连接
2. ATTP Tool Client — 将工具调用桥接到 ATTP 协议发送到远程工具节点

原有的 SendMessageTool 被整合为 bridge 的一部分。
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, Callable, Awaitable

import aiohttp
import uvicorn

from mcp.server.fastmcp import FastMCP

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG
from attp.core.sessions.node_message import NodeMessage

logger = get_logger("ToolBridge")

if TYPE_CHECKING:
    from attp.app.config.config import ToolConfig
    from attp.app.client import ATTPClient
    from attp.core.tracer import MessageTracer
    from attp.core.sessions import SessionManager


class ToolNodeInfo:
    """远程 ATTP 工具节点的注册信息。"""

    def __init__(
        self,
        did: str,
        name: str,
        description: str,
        attp_endpoint: str,
        tools: list[dict[str, Any]],
        public_key_endpoint: str = "",
    ):
        self.did = did
        self.name = name
        self.description = description
        self.attp_endpoint = attp_endpoint
        self.tools = tools  # [{"name": ..., "description": ..., "inputSchema": ...}]
        self.public_key_endpoint = public_key_endpoint


class MCPToolBridge:
    """Agent 侧：MCP Server + ATTP Tool Client 桥接器。

    使用方式：
        bridge = MCPToolBridge(tool_config, attp_client, tracer, session_manager)
        await bridge.start()

    nanobot 通过 MCP SSE 连接到此服务，可调用：
    - send_message_tool — 发送消息给 Agent/User（原有功能）
    - call_tool_node — 调用远程 ATTP 工具节点
    - list_tool_nodes — 列出已发现的远程工具节点
    """

    def __init__(
        self,
        tool_config: ToolConfig,
        attp_client: ATTPClient | None = None,
        tracer: MessageTracer | None = None,
        session_manager: SessionManager | None = None,
        agent_did: str = "",
        send_callback: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> None:
        """初始化桥接器。

        Args:
            tool_config: 工具服务配置（host/port）。
            attp_client: ATTP 客户端实例，用于发送 ATTP 消息到工具节点。
            tracer: MessageTracer 实例，用于行为溯源。
            session_manager: SessionManager 实例，用于会话管理。
            agent_did: 本 Agent 的 DID。
            send_callback: 消息发送回调（target, content, chat_id）-> str，
                          用于 send_message_tool 的实际发送逻辑。
        """
        self.host = tool_config.host
        self.port = tool_config.port
        self._attp_client = attp_client
        self._tracer = tracer
        self._session_manager = session_manager
        self._agent_did = agent_did
        self._send_callback = send_callback
        self._task: asyncio.Task | None = None
        self._uvicorn_server = None

        # 已发现的远程 ATTP 工具节点: tool_did -> ToolNodeInfo
        self._tool_nodes: dict[str, ToolNodeInfo] = {}

        # MCP Server 实例
        self._mcp = FastMCP("attp-tools")

        # 注册 MCP 工具
        self._register_tools()

    # ------------------------------------------------------------------
    # MCP Tool 注册
    # ------------------------------------------------------------------

    def _register_tools(self) -> None:
        """注册所有 MCP 工具到 FastMCP 实例。"""

        _send_cb = self._send_callback
        _call = self._call_tool_node
        _list = self._list_tool_nodes

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
                if _send_cb:
                    result = await _send_cb(target, content, chat_id)
                else:
                    result = "Error: no send callback configured"
            except Exception as exc:
                logger.exception("send_message callback failed")
                result = f"Error: {exc}"
            return result if isinstance(result, str) else str(result)

        @self._mcp.tool(
            name="call_tool_node",
            description=(
                "调用远程 ATTP 工具节点上的工具。"
                "通过 ATTP 协议安全地调用已注册的工具节点。\n\n"
                "参数说明：\n"
                "- tool_did: 目标工具节点的 DID\n"
                "- tool_name: 要调用的工具名称\n"
                "- arguments: 工具调用的参数（JSON 字符串）\n"
                "- chat_id: 当前会话ID，用于路由和溯源追踪"
            ),
        )
        async def call_tool_node(
            tool_did: str, tool_name: str, arguments: str, chat_id: str
        ) -> str:
            if not tool_did or not tool_name or not chat_id:
                return "Error: tool_did, tool_name and chat_id are all required."
            try:
                result = await _call(tool_did, tool_name, arguments, chat_id)
            except Exception as exc:
                logger.exception("call_tool_node failed")
                result = f"Error: {exc}"
            return result if isinstance(result, str) else str(result)

        @self._mcp.tool(
            name="list_tool_nodes",
            description=(
                "列出所有已发现的远程 ATTP 工具节点及其可用工具。"
                "返回每个工具节点的 DID、名称、描述和工具列表。"
            ),
        )
        async def list_tool_nodes() -> str:
            return await _list()

    # ------------------------------------------------------------------
    # ATTP Tool Client 逻辑
    # ------------------------------------------------------------------

    async def _call_tool_node(
        self, tool_did: str, tool_name: str, arguments: str, chat_id: str
    ) -> str:
        """通过 ATTP 协议调用远程工具节点。

        流程：
        1. 记录 field_type="A2T" (Agent→Tool)
        2. 构建 ATTP 元数据（含溯源链）
        3. 发送 tool_request 到工具节点的 ATTP 端点
        4. 接收 tool_response（含 T2A 溯源）
        """
        # 记录 A2T 行为
        if self._session_manager and self._tracer:
            session = self._session_manager.get_or_create(chat_id)
            trace = session.get_trace_metadata()
            origin_did = trace.get("Origin_DID", self._agent_did)
            hop_count = session._current_hop_count()

            nm = session.get_or_create_node_message(
                node_did=self._agent_did,
                origin_did=origin_did,
                hop_count=hop_count,
            )
            nm.add_entry(
                field_type="A2T",
                content=f"call_tool_node({tool_did}, {tool_name}, {arguments})",
                target=tool_did,
                tool_name=tool_name,
            )

            self._tracer.save_behavior_entry(
                session_id=chat_id,
                origin_did=origin_did,
                node_did=self._agent_did,
                hop_count=hop_count,
                field_type="A2T",
                content=f"call_tool_node({tool_did}, {tool_name}, {arguments})",
                target=tool_did,
                timestamp=time.time(),
            )
            self._session_manager.save(session)

        # 构建 ATTP 消息元数据
        metadata: dict[str, Any] = {
            "Session_ID": chat_id,
            "Tool_Name": tool_name,
            "Arguments": arguments,
        }

        # 追加溯源跳
        if self._tracer and self._attp_client:
            private_key_path = str(
                self._attp_client.auth.private_key_path
            ) if getattr(self._attp_client.auth, "private_key_path", None) else None

            if private_key_path:
                try:
                    metadata = self._tracer.append_hop(
                        metadata=metadata,
                        content=f"tool_call:{tool_name}",
                        node_did=self._agent_did,
                        target_did=tool_did,
                        private_key_path=private_key_path,
                    )
                except Exception as e:
                    logger.error("Failed to append tracing hop for tool call: {}", e)

        # 发送到工具节点的 ATTP 端点
        tool_info = self._tool_nodes.get(tool_did)
        if not tool_info:
            return f"Error: Tool node {tool_did} not found. Use list_tool_nodes to discover available tools."

        endpoint = tool_info.attp_endpoint
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    json={
                        "sender_did": self._agent_did,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "message_type": "tool_request",
                        "metadata": metadata,
                    },
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("result", str(result))
                    else:
                        error_text = await resp.text()
                        return f"Error: Tool node returned HTTP {resp.status}: {error_text}"
        except aiohttp.ClientError as e:
            logger.error("Failed to call tool node {}: {}", tool_did, e)
            return f"Error: Failed to reach tool node {tool_did}: {e}"

    async def _list_tool_nodes(self) -> str:
        """列出所有已注册的远程工具节点。"""
        if not self._tool_nodes:
            return "No remote ATTP tool nodes registered."

        lines = ["Registered ATTP Tool Nodes:"]
        for did, info in self._tool_nodes.items():
            lines.append(f"\n  DID: {did}")
            lines.append(f"  Name: {info.name}")
            lines.append(f"  Description: {info.description}")
            lines.append(f"  Endpoint: {info.attp_endpoint}")
            if info.tools:
                lines.append("  Available Tools:")
                for tool in info.tools:
                    lines.append(f"    - {tool.get('name', 'unknown')}: {tool.get('description', '')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 工具节点注册 / 发现
    # ------------------------------------------------------------------

    def register_tool_node(self, tool_info: ToolNodeInfo) -> None:
        """注册一个远程 ATTP 工具节点。"""
        self._tool_nodes[tool_info.did] = tool_info
        logger.info("Registered tool node: {} ({})", tool_info.name, tool_info.did)

    async def discover_tool_node(self, ad_url: str) -> ToolNodeInfo | None:
        """从 ad.json URL 发现并注册远程工具节点。

        Args:
            ad_url: 工具节点的 ad.json 地址。

        Returns:
            ToolNodeInfo 或 None（发现失败时）。
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(ad_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.error("Failed to fetch tool ad from {}: HTTP {}", ad_url, resp.status)
                        return None
                    ad_data = await resp.json()

            # 验证 ad 类型
            if ad_data.get("type") != "attp-tool-node":
                logger.error("Invalid ad type from {}: {}", ad_url, ad_data.get("type"))
                return None

            tool_info = ToolNodeInfo(
                did=ad_data.get("identifier", ""),
                name=ad_data.get("name", ""),
                description=ad_data.get("description", ""),
                attp_endpoint=ad_data.get("attp_endpoint", ""),
                tools=ad_data.get("mcp_tools", []),
                public_key_endpoint=ad_data.get("public_key_endpoint", ""),
            )

            if not tool_info.did or not tool_info.attp_endpoint:
                logger.error("Tool ad missing required fields: identifier/attp_endpoint")
                return None

            self.register_tool_node(tool_info)
            return tool_info
        except Exception as e:
            logger.error("Failed to discover tool node at {}: {}", ad_url, e)
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the MCP SSE server in the background."""
        if self._task is not None and not self._task.done():
            logger.warning("already running")
            return

        starlette_app = self._mcp.sse_app()
        config = uvicorn.Config(
            starlette_app,
            host=self.host,
            port=self.port,
            log_level="info",
            log_config=UVICORN_SILENT_LOG_CONFIG,
        )
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
        """Stop → update host/port → restart. Callbacks remain unchanged."""
        await self.stop()
        self.host = tool_config.host
        self.port = tool_config.port
        await self.start()
        logger.info("reloaded on {}:{}", self.host, self.port)