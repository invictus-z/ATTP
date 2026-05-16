"""ATTPToolNode — 将 MCP 工具服务包装为 ATTP 工具节点。

这是 SDK 的核心类，提供：
1. ATTP Server — 接收来自 Agent 的 tool_request，返回 tool_response
2. 溯源链 — 对每次工具调用进行签名和验签
3. ad.json 生成 — 自动生成服务描述文件供 Agent 发现
4. T2A 行为记录 — 记录 Tool→Agent 的响应行为

使用方式：
    from attp.sdk.tools import ATTPToolNode, ToolHandler

    node = ATTPToolNode(
        did="did:wba:tool-server.local:my-tool",
        name="my-tool-server",
        private_key_path="key.pem",
        host="0.0.0.0",
        port=9000,
    )

    @node.tool("search", "搜索知识库", {"type": "object", "properties": {...}})
    async def search(query: str, limit: int = 10):
        return {"results": [...]}

    await node.start()
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Awaitable

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from attp.core.authentication.keys import KeyStore, load_private_key
from attp.core.authentication.signatures import sign_hash, verify_signature
from attp.core.provenance.hashing import calculate_hop_hash
from attp.core.provenance.chain import ChainManager
from attp.core.sessions.node_message import NodeMessage
from attp.core.storage.sqlite_store import SqliteStore
from attp.core.pn_tracer import ProtocolTracer
from attp.sdk.tools.handler import ToolHandler
from attp.sdk.tools.tool_ad import ToolAd

import logging

logger = logging.getLogger("attp.sdk.tools.tool_node")


class ATTPToolNode:
    """ATTP 工具节点 — 将 MCP 工具服务包装为 ATTP 网络中的工具节点。

    功能：
    - 接收 Agent 发来的 tool_request（ATTP 协议）
    - 路由到对应 ToolHandler 执行
    - 记录 T2A（Tool→Agent）行为溯源
    - 追加溯源跳 + 签名
    - 返回 tool_response
    - 自动生成 ad.json
    """

    def __init__(
        self,
        did: str,
        name: str,
        private_key_path: str,
        host: str = "0.0.0.0",
        port: int = 9000,
        description: str = "",
        db_path: str = "tool_node_traces.db",
        ad_output_path: str | None = None,
        attp_prefix: str = "/attp",
    ):
        """初始化 ATTP 工具节点。

        Args:
            did: 工具节点的 DID 标识。
            name: 工具节点名称。
            private_key_path: 私钥 PEM 文件路径，用于 ATTP 签名。
            host: 监听地址。
            port: 监听端口。
            description: 工具节点描述。
            db_path: 行为溯源数据库路径。
            ad_output_path: ad.json 输出路径，默认为当前目录。
            attp_prefix: ATTP 端点 URL 路径前缀。
        """
        self.did = did
        self.name = name
        self.description = description
        self.host = host
        self.port = port
        self.private_key_path = Path(private_key_path).expanduser()
        self.attp_prefix = attp_prefix

        # 工具处理器注册表: tool_name -> ToolHandler
        self._handlers: dict[str, ToolHandler] = {}

        # 溯源子系统
        self._key_store = KeyStore()
        self._chain = ChainManager(self._key_store)
        self._storage = SqliteStore(db_path)
        self._tracer = ProtocolTracer(db_path)

        # FastAPI 应用
        self._app = FastAPI(title=f"ATTP Tool Node: {name}")
        self._setup_routes()

        # 生命周期
        self._uvicorn_server = None
        self._serve_task = None

        # ad.json
        self._ad_output_path = Path(ad_output_path) if ad_output_path else Path("ad.json")

    # ------------------------------------------------------------------
    # 工具注册（装饰器 + 方法）
    # ------------------------------------------------------------------

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> Callable:
        """装饰器：注册一个工具处理器。

        用法：
            @node.tool("search", "搜索", {"type": "object", "properties": {...}})
            async def search(query: str, limit: int = 10):
                return {"results": [...]}
        """
        def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            self.register_handler(ToolHandler(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=func,
            ))
            return func
        return decorator

    def register_handler(self, handler: ToolHandler) -> None:
        """注册一个 ToolHandler。"""
        if handler.name in self._handlers:
            logger.warning("Overwriting existing handler: %s", handler.name)
        self._handlers[handler.name] = handler
        logger.info("Registered tool handler: %s", handler.name)

    # ------------------------------------------------------------------
    # ATTP 请求处理
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        """设置 FastAPI 路由。"""

        @self._app.post(self.attp_prefix)
        async def handle_attp_request(request: Request) -> JSONResponse:
            """ATTP 协议端点 — 处理 tool_request / tool_response / record。"""
            try:
                body = await request.json()
            except Exception:
                return JSONResponse(
                    {"error": "Invalid JSON body"},
                    status_code=400,
                )

            message_type = body.get("message_type", "")

            if message_type == "tool_request":
                return await self._handle_tool_request(body)
            elif message_type == "record":
                return await self._handle_record(body)
            else:
                return JSONResponse(
                    {"error": f"Unknown message_type: {message_type}"},
                    status_code=400,
                )

        @self._app.get(f"{self.attp_prefix}/ad.json")
        async def get_ad(request: Request) -> JSONResponse:
            """返回工具节点的 ad.json。"""
            return JSONResponse(self._build_ad().to_dict())

        @self._app.get(f"{self.attp_prefix}/health")
        async def health(request: Request) -> JSONResponse:
            """健康检查。"""
            return JSONResponse({"status": "ok", "did": self.did})

    async def _handle_tool_request(self, body: dict) -> JSONResponse:
        """处理 tool_request 消息。

        流程：
        1. 解析参数，查找 handler
        2. 验证溯源链（如果 metadata 中有 Hop）
        3. 执行工具
        4. 记录 T2A 行为
        5. 追加溯源跳 + 签名
        6. 返回 tool_response
        """
        sender_did = body.get("sender_did", "")
        tool_name = body.get("tool_name", "")
        arguments_str = body.get("arguments", "{}")
        metadata = body.get("metadata", {})
        session_id = metadata.get("Session_ID", "")

        # 1. 查找 handler
        handler = self._handlers.get(tool_name)
        if not handler:
            return JSONResponse(
                {"error": f"Tool not found: {tool_name}"},
                status_code=404,
            )

        # 2. 解析参数
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": f"Invalid arguments JSON: {arguments_str}"},
                status_code=400,
            )

        # 3. 验证溯源链（可选）
        hop_data = metadata.get("Hop")
        if hop_data:
            try:
                is_valid, error = self._chain.validate_hop(
                    hop_data,
                    prev_hop_count=hop_data.get("Hop_Count", 0) - 1,
                )
                if not is_valid:
                    logger.warning("Hop validation failed: %s", error)
            except Exception as e:
                logger.warning("Hop validation error: %s", e)

        # 4. 执行工具
        try:
            result = await handler(**arguments)
            result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return JSONResponse(
                {"error": f"Tool execution failed: {str(e)}"},
                status_code=500,
            )

        # 5. 记录 T2A 行为溯源
        origin_did = metadata.get("Origin_DID", sender_did)
        hop_count = metadata.get("Hop", {}).get("Hop_Count", 0) + 1

        if session_id:
            try:
                # 记录 T2A 行为到数据库
                self._tracer.save_behavior_entry(
                    session_id=session_id,
                    origin_did=origin_did,
                    node_did=self.did,
                    hop_count=hop_count,
                    field_type="T2A",
                    content=f"tool_response({tool_name}): {result_str[:500]}",
                    target=sender_did,
                    timestamp=time.time(),
                )
            except Exception as e:
                logger.warning("Failed to save T2A behavior: %s", e)

        # 6. 追加溯源跳 + 签名
        response_metadata = dict(metadata)
        try:
            response_metadata = self._tracer.append_hop(
                metadata=response_metadata,
                content=f"tool_response:{tool_name}",
                node_did=self.did,
                target_did=sender_did,
                private_key_path=str(self.private_key_path),
            )
        except Exception as e:
            logger.error("Failed to append hop: %s", e)

        # 7. 返回 tool_response
        return JSONResponse({
            "result": result_str,
            "tool_name": tool_name,
            "tool_did": self.did,
            "message_type": "tool_response",
            "metadata": response_metadata,
        })

    async def _handle_record(self, body: dict) -> JSONResponse:
        """处理 record 消息 — 保存远端 NodeMessage。"""
        metadata = body.get("metadata", {})
        node_msg_data = metadata.get("NodeMessage")

        if node_msg_data:
            try:
                node_message = NodeMessage.from_dict(node_msg_data)
                self._tracer.save_node_message(node_message)
                logger.info(
                    "NodeMessage saved from node=%s, hop=%d",
                    node_message.node_did,
                    node_message.hop_count,
                )
            except Exception as e:
                logger.warning("Failed to save NodeMessage: %s", e)

        return JSONResponse({"status": "Record saved"})

    # ------------------------------------------------------------------
    # ad.json
    # ------------------------------------------------------------------

    def _build_ad(self) -> ToolAd:
        """根据当前注册的 handlers 构建 ToolAd。"""
        attp_endpoint = f"http://{self.host}:{self.port}{self.attp_prefix}"
        # 如果 host 是 0.0.0.0，使用 localhost 作为 ad 中的地址
        if self.host == "0.0.0.0":
            attp_endpoint = f"http://localhost:{self.port}{self.attp_prefix}"

        return ToolAd(
            did=self.did,
            name=self.name,
            description=self.description,
            attp_endpoint=attp_endpoint,
            mcp_tools=[h.to_mcp_tool_dict() for h in self._handlers.values()],
        )

    def generate_ad(self, output_path: str | None = None) -> ToolAd:
        """生成并保存 ad.json 文件。

        Args:
            output_path: 输出路径，默认使用构造时的 ad_output_path。

        Returns:
            生成的 ToolAd 对象。
        """
        ad = self._build_ad()
        path = Path(output_path) if output_path else self._ad_output_path
        ad.save_to_file(path)
        logger.info("Generated ad.json at %s", path)
        return ad

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 ATTP 工具节点服务。"""
        # 自动生成 ad.json
        self.generate_ad()

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(config)

        async def _run():
            await self._uvicorn_server.serve()

        self._serve_task = asyncio.create_task(_run())
        logger.info(
            "ATTP Tool Node '%s' started at %s:%d (DID: %s)",
            self.name, self.host, self.port, self.did,
        )

    async def stop(self) -> None:
        """停止 ATTP 工具节点服务。"""
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
        logger.info("ATTP Tool Node '%s' stopped", self.name)