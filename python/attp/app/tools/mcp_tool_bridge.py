"""MCPToolBridge — Agent 侧工具桥接器。

同时充当：
1. MCP SSE Server — 暴露给 nanobot（Agent 内置 MCP Client）连接
2. ATTP Tool Client — 将工具调用桥接到 ATTP 协议发送到远程工具节点

核心功能：
- send_message_tool — 发送消息给 Agent/User
- 动态注册远程工具节点工具 — 每个远程工具自动注册为独立 MCP Tool
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import TYPE_CHECKING, Any, Callable, Awaitable

import aiohttp
import uvicorn

from mcp.server.fastmcp import FastMCP

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG
from attp.core.message.event import NodeMessage, RecordedHop
from attp.core.message.back_sender import send_back_message, BackPropagationError

logger = get_logger("ToolBridge")

if TYPE_CHECKING:
    from attp.app.config.config import ToolConfig
    from attp.app.client import ATTPClient
    from attp.core.agent_tracer import AgentTracer
    from attp.core.sessions.app import AppSessionManager


# ------------------------------------------------------------------
# PassthroughArgModel — 透传所有参数给 handler
# ------------------------------------------------------------------

def _make_passthrough_arg_model_class():
    """延迟导入并创建 PassthroughArgModel。

    避免在模块顶层依赖 mcp 内部路径，仅在动态注册远程工具时才导入。
    """
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase, FuncMetadata

    from pydantic import ConfigDict

    class PassthroughArgModel(ArgModelBase):
        """透传所有参数的 ArgModel — 接受任意字段并原样返回。

        用于动态注册的远程工具，因为远程工具的参数无法在函数签名中表达，
        需要在运行时透传所有参数给 handler。
        """
        model_config = ConfigDict(extra="allow")

        def model_dump_one_level(self) -> dict[str, Any]:
            kwargs = {}
            for field_name, field_info in self.__class__.model_fields.items():
                value = getattr(self, field_name)
                output_name = field_info.alias if field_info.alias else field_name
                kwargs[output_name] = value
            # 透传 extra 字段（远程工具的实际参数）
            if self.__pydantic_extra__:
                kwargs.update(self.__pydantic_extra__)
            return kwargs

    return PassthroughArgModel, FuncMetadata


# ------------------------------------------------------------------
# ToolNodeInfo
# ------------------------------------------------------------------

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
        ad_url: str = "",          # 来源 ad.json URL，用于心跳恢复
    ):
        self.did = did
        self.name = name
        self.description = description
        self.attp_endpoint = attp_endpoint
        self.tools = tools  # [{"name": ..., "description": ..., "inputSchema": ...}]
        self.public_key_endpoint = public_key_endpoint
        self.ad_url = ad_url


# ------------------------------------------------------------------
# MCPToolBridge
# ------------------------------------------------------------------

class MCPToolBridge:
    """Agent 侧：MCP Server + ATTP Tool Client 桥接器。

    使用方式：
        bridge = MCPToolBridge(tool_config, attp_client, tracer, session_manager)
        await bridge.start()

    nanobot 通过 MCP SSE 连接到此服务，可调用：
    - send_message_tool — 发送消息给 Agent/User
    - 动态注册的远程工具 — 每个远程工具节点上的工具自动注册为独立 MCP Tool
    """

    def __init__(
        self,
        tool_config: ToolConfig,
        attp_client: ATTPClient | None = None,
        tracer: AgentTracer | None = None,
        session_manager: AppSessionManager | None = None,
        agent_did: str = "",
        send_callback: Callable[[str, str, str], Awaitable[str]] | None = None,
    ) -> None:
        """初始化桥接器。

        Args:
            tool_config: 工具服务配置（host/port）。
            attp_client: ATTP 客户端实例，用于发送 ATTP 消息到工具节点。
            tracer: AgentTracer 实例，用于行为溯源。
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

        # 动态工具映射: did -> [mcp_tool_names]
        self._node_tool_map: dict[str, list[str]] = {}

        # 并发保护
        self._registry_lock = asyncio.Lock()

        # MCP Server 实例
        self._mcp = FastMCP("attp-tools")

        # 注册核心工具
        self._register_core_tools()

    # ------------------------------------------------------------------
    # 核心工具注册
    # ------------------------------------------------------------------

    def _register_core_tools(self) -> None:
        """注册核心 MCP 工具（send_message_tool）。"""

        _send_cb = self._send_callback

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

    # ------------------------------------------------------------------
    # 动态工具注册 / 注销
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_mcp_name(node_name: str, tool_name: str, did: str) -> str:
        """生成 MCP 工具名：{sanitized_node_name}_{did_hash}__{tool_name}

        使用 DID 哈希后缀避免不同节点同名冲突。
        """
        slug = re.sub(r'[^a-zA-Z0-9_]', '_', node_name).lower().strip('_')
        did_hash = did.split(':')[-1][:8] if did else 'unknown'
        return f"{slug}_{did_hash}__{tool_name}"

    def _register_remote_tool(
        self,
        tool_did: str,
        tool_name: str,
        mcp_name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> None:
        """动态注册一个远程工具到 FastMCP。

        绕过 add_tool() 的函数签名内省，直接构造 Tool 对象，
        使用远程工具的真实 inputSchema 作为参数 schema。
        """
        from mcp.server.fastmcp.tools.base import Tool as MCPTool

        PassthroughArgModel, FuncMetadata = _make_passthrough_arg_model_class()

        _call = self._call_tool_node

        async def handler(**kwargs: Any) -> str:
            chat_id = kwargs.pop("chat_id", "") # 要求填入 chat_id 以便 ATTP 消息追踪
            arguments = json.dumps(kwargs, ensure_ascii=False)
            return await _call(tool_did, tool_name, arguments, chat_id)

        # 创建透传 fn_metadata
        passthrough_model = type(f"{mcp_name}_args", (PassthroughArgModel,), {})
        passthrough_metadata = FuncMetadata(arg_model=passthrough_model)

        # 直接构造 Tool 对象，使用远程工具的 inputSchema
        tool = MCPTool(
            fn=handler,
            name=mcp_name,
            description=description,
            parameters=input_schema,            # 远程工具的真实 schema
            fn_metadata=passthrough_metadata,    # 透传参数
            is_async=True,
            context_kwarg=None,
        )

        # 注册到 tool manager
        self._mcp._tool_manager._tools[mcp_name] = tool
        logger.info("Dynamically registered remote tool: {}", mcp_name)

    def _unregister_remote_tool(self, mcp_name: str) -> None:
        """从 FastMCP tool manager 中移除指定工具。"""
        try:
            self._mcp._tool_manager._tools.pop(mcp_name, None)
        except Exception as e:
            logger.warning("Failed to remove tool {}: {}", mcp_name, e)

    async def register_tool_node(self, tool_info: ToolNodeInfo) -> None:
        """注册远程工具节点 + 动态注册每个工具到 FastMCP。"""
        async with self._registry_lock:
            self._tool_nodes[tool_info.did] = tool_info
            mcp_names: list[str] = []

            for tool_def in tool_info.tools:
                tool_name = tool_def.get("name", "unknown")
                mcp_name = self._build_tool_mcp_name(tool_info.name, tool_name, tool_info.did)
                description = (
                    f"[来自工具节点 {tool_info.name} ({tool_info.did})]\n"
                    f"{tool_def.get('description', '')}"
                )
                input_schema = tool_def.get("inputSchema", {"type": "object", "properties": {}})

                self._register_remote_tool(
                    tool_did=tool_info.did,
                    tool_name=tool_name,
                    mcp_name=mcp_name,
                    description=description,
                    input_schema=input_schema,
                )
                mcp_names.append(mcp_name)

            self._node_tool_map[tool_info.did] = mcp_names
            logger.info(
                "Registered tool node: {} ({}) with {} tools",
                tool_info.name, tool_info.did, len(mcp_names),
            )

    async def unregister_tool_node(self, did: str) -> None:
        """移除远程工具节点 + 清理所有已注册的 MCP 工具。"""
        async with self._registry_lock:
            tool_names = self._node_tool_map.pop(did, [])
            for mcp_name in tool_names:
                self._unregister_remote_tool(mcp_name)

            self._tool_nodes.pop(did, None)
            logger.info("Unregistered tool node: {} ({} tools removed)", did, len(tool_names))

    def get_tool_nodes(self) -> dict[str, ToolNodeInfo]:
        """返回当前已注册工具节点的快照（公开接口）。"""
        return dict(self._tool_nodes)

    # ------------------------------------------------------------------
    # ATTP Tool Client 逻辑
    # ------------------------------------------------------------------

    async def _call_tool_node(
        self, tool_did: str, tool_name: str, arguments: str, chat_id: str
    ) -> str:
        """通过 ATTP 协议调用远程工具节点。

        完整流程（4 次回传）：
        === 第一跳 A2T (Agent → Tool) ===
        1. 通过 AgentTracer.append_hop 构建 RecordedHop_A2T（正确递增 hop_count）
        2. 发送 BackMessage #1 (Phase 2, Agent 报告) → Protocol Node（严格门控）
        3. 发送 NodeMessage(A2T) → Tool Node

        === 第二跳 T2A (Tool → Agent) ===
        4. 等待 tool_response（含 NodeMessage(T2A)），hop_count 保持不变
        5. 发送 BackMessage #4 (Phase 1, Agent 确认) → Protocol Node（严格门控）
        """
        tool_info = self._tool_nodes.get(tool_did)
        if not tool_info:
            return f"Error: Tool node {tool_did} not found."

        # 获取私钥和协议节点地址
        private_key_path = None
        private_key = None
        if self._attp_client:
            private_key_path = (
                str(self._attp_client.auth.private_key_path)
                if getattr(self._attp_client.auth, "private_key_path", None)
                else None
            )
            if private_key_path and self._tracer:
                try:
                    private_key = self._tracer.load_private_key(private_key_path)
                except Exception as e:
                    logger.error("Failed to load private key: {}", e)

        # 从 session 获取 trace metadata（和 send_to_agent 一样）
        metadata: dict[str, Any] = {"Session_ID": chat_id}
        if self._session_manager and chat_id:
            session = self._session_manager.get(chat_id)
            if session:
                trace = session.get_trace_metadata()
                if trace:
                    metadata.update(trace)

        # -- 通过 AgentTracer.append_hop 正确递增 hop_count --
        nonce = uuid.uuid4().hex
        metadata["nonce"] = nonce

        if private_key_path and self._tracer:
            try:
                metadata = self._tracer.append_hop(
                    metadata=metadata,
                    content=f"tool_call:{tool_name} args={arguments}",
                    node_did=self._agent_did,
                    target_did=tool_did,
                    private_key_path=private_key_path,
                    behavior_type="A2T",
                )
            except Exception as e:
                logger.error("Failed to append tracing hop: {}", e)
                return f"Error: Tracing hook failed - {e}"

        hop = metadata.get("Hop")
        if not hop:
            return "Error: Hop metadata not generated"

        protocol_node_address = metadata.get("Protocol_Node_Address", "")

        recorded_hop_a2t = RecordedHop(
            session_id=metadata["Session_ID"],
            sender_did=hop["node_did"],
            target_did=hop["target_did"],
            content=hop["Content"],
            timestamp=hop["Timestamp"],
            hop_count=hop["Hop_Count"],
            sig_content=hop["Signature"],
        )

        # -- 构建 NodeMessage(A2T) --
        node_message_a2t = NodeMessage(
            protocol_url=protocol_node_address,
            nonce=nonce,
            recorded_hop=recorded_hop_a2t,
        )

        endpoint = tool_info.attp_endpoint

        # === 第一跳 A2T: BackMessage #1 (Phase 2, Agent 报告) → Protocol Node ===
        if protocol_node_address and private_key:
            try:
                await send_back_message(
                    protocol_url=protocol_node_address,
                    node_did=self._agent_did,
                    nonce=nonce,
                    recorded_hop=recorded_hop_a2t,
                    private_key=private_key,
                )
            except BackPropagationError as e:
                return f"Error: BackMessage #1 failed: {e}"

        # === 第一跳 A2T: 发送 tool_request 到 Tool Node ===
        try:
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(
                    endpoint,
                    json={
                        "sender_did": self._agent_did,
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "message_type": "tool_request",
                        "node_message": node_message_a2t.to_dict(),
                    },
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        return f"Error: Tool node returned HTTP {resp.status}: {error_text}"
                    result_body = await resp.json()
        except aiohttp.ClientError as e:
            logger.error("Failed to call tool node {}: {}", tool_did, e)
            return f"Error: Failed to reach tool node {tool_did}: {e}"

        # === 第二跳 T2A: 解析 tool_response 中的 NodeMessage(T2A) ===
        # T2A 的 hop_count 保持工具节点返回的值不变（不递增）
        node_message_t2a_data = result_body.get("node_message")
        if node_message_t2a_data and protocol_node_address and private_key:
            try:
                node_message_t2a = NodeMessage.from_dict(node_message_t2a_data)
                recorded_hop_t2a = node_message_t2a.recorded_hop

                # BackMessage #4 (Phase 1, Agent 确认 T2A)
                await send_back_message(
                    protocol_url=protocol_node_address,
                    node_did=self._agent_did,
                    nonce=node_message_t2a.nonce,
                    recorded_hop=recorded_hop_t2a,
                    private_key=private_key,
                )
            except BackPropagationError as e:
                return f"Error: BackMessage #4 failed: {e}"
            except Exception as e:
                logger.warning("Failed to process T2A NodeMessage: {}", e)

        # 更新 session 的 trace metadata
        if self._session_manager and chat_id and "Hop" in metadata:
            session = self._session_manager.get_or_create(chat_id)
            session.set_trace_metadata({
                "Hop": metadata["Hop"],
                "Session_ID": metadata["Session_ID"],
                "Protocol_Node_Address": metadata.get("Protocol_Node_Address"),
            })
            self._session_manager.save(session)

        return result_body.get("result", str(result_body))

    # ------------------------------------------------------------------
    # 工具节点发现
    # ------------------------------------------------------------------

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
                ad_url=ad_url,
            )

            if not tool_info.did or not tool_info.attp_endpoint:
                logger.error("Tool ad missing required fields: identifier/attp_endpoint")
                return None

            await self.register_tool_node(tool_info)
            return tool_info
        except Exception as e:
            logger.error("Failed to discover tool node at {}: {}", ad_url, e)
            return None

    async def discover_all_tool_nodes(self, ad_urls: list[str]) -> None:
        """并行发现并注册工具节点。"""
        results = await asyncio.gather(
            *[self.discover_tool_node(url) for url in ad_urls],
            return_exceptions=True,
        )
        for url, result in zip(ad_urls, results):
            if isinstance(result, Exception):
                logger.error("Failed to discover tool node at {}: {}", url, result)

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