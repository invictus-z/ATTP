"""MCPProxyToolNode — MCP Config 代理，将远程 MCP 服务包装为 ATTP 工具节点。

适用场景：外部 MCP 服务（如 web-reader、code-interpreter），
通过 JSON 配置文件接入 ATTP 网络，无需修改远程服务。

与 MCPToATTPAdapter 的区别：
- MCPToATTPAdapter：包装本地已有 MCP Server 实例（同进程）
- MCPProxyToolNode：连接远程 MCP 服务（跨进程/跨网络），作为本地代理网关

签名方：本地代理（非远程服务），代理持有 DID 和私钥

使用方式：
    from attp.sdk.tools import MCPProxyToolNode

    proxy = MCPProxyToolNode(
        did="did:wba:proxy.local:web-reader",
        name="web-reader-proxy",
        private_key_path="key.pem",
        config={
            "mcpServers": {
                "web-reader": {
                    "type": "streamableHttp",
                    "url": "https://open.bigmodel.cn/api/mcp/web_reader/mcp",
                    "headers": {"Authorization": "Bearer xxx"}
                }
            }
        },
        port=9001,
    )

    await proxy.start()  # 自动发现远程工具，暴露为 ATTP 端点
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import aiohttp
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from attp.core.authentication.keys import KeyStore
from attp.core.provenance.chain import ChainManager
from attp.core.sessions.node_message import NodeMessage
from attp.core.storage.sqlite_store import SqliteStore
from attp.core.pn_tracer import ProtocolTracer
from attp.sdk.tools.tool_ad import ToolAd

import logging

logger = logging.getLogger("attp.sdk.tools.mcp_proxy")


class MCPProxyToolNode:
    """MCP Config 代理 — 将远程 MCP 服务包装为 ATTP 工具节点。

    本地代理持有 DID 和私钥，负责：
    1. 连接远程 MCP 服务，获取工具列表
    2. 暴露 ATTP 端点，接收 tool_request
    3. 转发请求到远程 MCP 服务
    4. 对响应进行签名，记录溯源链
    """

    def __init__(
        self,
        did: str,
        name: str,
        private_key_path: str,
        config: dict[str, Any],
        host: str = "0.0.0.0",
        port: int = 9000,
        description: str = "",
        db_path: str = "tool_node_traces.db",
        ad_output_path: str | None = None,
        attp_prefix: str = "/attp",
    ):
        """
        Args:
            did: 代理节点的 DID 标识。
            name: 代理节点名称。
            private_key_path: 本地代理的私钥 PEM 文件路径。
            config: MCP 服务配置，格式同 mcpServers 配置文件。
                    例如: {"mcpServers": {"web-reader": {"type": "streamableHttp", "url": "...", "headers": {...}}}}
            host: 监听地址。
            port: 监听端口。
            description: 代理节点描述。
            db_path: 溯源数据库路径。
            ad_output_path: ad.json 输出路径。
            attp_prefix: ATTP 端点 URL 路径前缀。
        """
        self.did = did
        self.name = name
        self.description = description
        self.host = host
        self.port = port
        self.private_key_path = Path(private_key_path).expanduser()
        self.attp_prefix = attp_prefix
        self._config = config

        # 溯源子系统
        self._key_store = KeyStore()
        self._chain = ChainManager(self._key_store)
        self._storage = SqliteStore(db_path)
        self._tracer = ProtocolTracer(db_path)

        # 远程工具缓存: server_name -> list of tool dicts
        self._remote_tools: dict[str, list[dict[str, Any]]] = {}
        # 扁平化工具索引: tool_name -> (server_name, server_config)
        self._tool_index: dict[str, tuple[str, dict[str, Any]]] = {}

        # FastAPI 应用
        self._app = FastAPI(title=f"ATTP Tool Proxy: {name}")
        self._setup_routes()

        # 生命周期
        self._uvicorn_server = None
        self._serve_task = None

        # ad.json
        self._ad_output_path = Path(ad_output_path) if ad_output_path else Path("ad.json")

    # ------------------------------------------------------------------
    # 远程 MCP 服务发现
    # ------------------------------------------------------------------

    async def discover_remote_tools(self) -> None:
        """连接配置中的所有远程 MCP 服务，获取工具列表。"""
        mcp_servers = self._config.get("mcpServers", {})

        for server_name, server_config in mcp_servers.items():
            try:
                tools = await self._fetch_tools_from_server(server_name, server_config)
                self._remote_tools[server_name] = tools

                for tool in tools:
                    tool_name = tool.get("name", "")
                    if tool_name:
                        self._tool_index[tool_name] = (server_name, server_config)

                logger.info(
                    "Discovered %d tools from '%s': %s",
                    len(tools), server_name,
                    [t.get("name", "?") for t in tools],
                )
            except Exception as e:
                logger.error("Failed to discover tools from '%s': %s", server_name, e)

    async def _fetch_tools_from_server(
        self, server_name: str, server_config: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """从远程 MCP 服务获取工具列表。

        支持 streamableHttp 和 sse 两种传输类型。
        通过发送 MCP initialize + tools/list 协议消息获取工具列表。
        """
        server_type = server_config.get("type", "sse")
        url = server_config.get("url", "")
        headers = server_config.get("headers", {})

        if not url:
            raise ValueError(f"Server '{server_name}' missing 'url'")

        # 构建 MCP 请求
        request_headers = {
            "Content-Type": "application/json",
            **headers,
        }

        async with aiohttp.ClientSession() as session:
            # 1. Initialize
            init_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": f"attp-proxy-{self.name}",
                        "version": "0.1.0",
                    },
                },
            }

            async with session.post(
                url, json=init_payload, headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Initialize failed: HTTP {resp.status}: {text}")
                init_result = await resp.json()

            # 2. Send initialized notification
            notif_payload = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
            async with session.post(
                url, json=notif_payload, headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                pass  # notification, no response expected

            # 3. List tools
            tools_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            }

            async with session.post(
                url, json=tools_payload, headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"tools/list failed: HTTP {resp.status}: {text}")
                tools_result = await resp.json()

        # 解析工具列表
        tools = []
        for tool_info in tools_result.get("result", {}).get("tools", []):
            tools.append({
                "name": tool_info.get("name", ""),
                "description": tool_info.get("description", ""),
                "inputSchema": tool_info.get("inputSchema", {}),
            })

        return tools

    # ------------------------------------------------------------------
    # 远程 MCP 工具调用
    # ------------------------------------------------------------------

    async def _call_remote_tool(
        self,
        server_config: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> str:
        """通过 MCP 协议调用远程工具。"""
        url = server_config.get("url", "")
        headers = server_config.get("headers", {})

        request_headers = {
            "Content-Type": "application/json",
            **headers,
        }

        call_payload = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json=call_payload, headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"tools/call failed: HTTP {resp.status}: {text}")
                result = await resp.json()

        # 解析结果
        result_data = result.get("result", {})
        content_list = result_data.get("content", [])

        if isinstance(content_list, list):
            parts = []
            for item in content_list:
                if isinstance(item, dict):
                    parts.append(item.get("text", str(item)))
                else:
                    parts.append(str(item))
            return "\n".join(parts)
        return json.dumps(result_data, ensure_ascii=False)

    # ------------------------------------------------------------------
    # ATTP 端点
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        @self._app.post(self.attp_prefix)
        async def handle_attp_request(request: Request) -> JSONResponse:
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

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
            return JSONResponse(self._build_ad().to_dict())

        @self._app.get(f"{self.attp_prefix}/health")
        async def health(request: Request) -> JSONResponse:
            return JSONResponse({"status": "ok", "did": self.did, "proxy": True})

    async def _handle_tool_request(self, body: dict) -> JSONResponse:
        """处理 tool_request → 转发到远程 MCP 服务 → 签名返回。"""
        sender_did = body.get("sender_did", "")
        tool_name = body.get("tool_name", "")
        arguments_str = body.get("arguments", "{}")
        metadata = body.get("metadata", {})
        session_id = metadata.get("Session_ID", "")

        # 查找工具对应的远程服务
        tool_entry = self._tool_index.get(tool_name)
        if not tool_entry:
            return JSONResponse(
                {"error": f"Tool not found: {tool_name}"},
                status_code=404,
            )

        server_name, server_config = tool_entry

        # 解析参数
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": f"Invalid arguments JSON: {arguments_str}"},
                status_code=400,
            )

        # 调用远程 MCP 服务
        try:
            result_str = await self._call_remote_tool(server_config, tool_name, arguments)
        except Exception as e:
            logger.exception("Remote MCP call failed: %s/%s", server_name, tool_name)
            return JSONResponse(
                {"error": f"Remote tool execution failed: {str(e)}"},
                status_code=502,
            )

        # 记录 T2A 行为溯源（本地代理签名）
        origin_did = metadata.get("Origin_DID", sender_did)
        hop_count = metadata.get("Hop", {}).get("Hop_Count", 0) + 1

        if session_id:
            try:
                self._tracer.save_behavior_entry(
                    session_id=session_id,
                    origin_did=origin_did,
                    node_did=self.did,
                    hop_count=hop_count,
                    field_type="T2A",
                    content=f"tool_response({tool_name}, proxy={server_name}): {result_str[:500]}",
                    target=sender_did,
                    timestamp=time.time(),
                )
            except Exception as e:
                logger.warning("Failed to save T2A behavior: %s", e)

        # 追加溯源跳 + 本地代理签名
        response_metadata = dict(metadata)
        try:
            response_metadata = self._tracer.append_hop(
                metadata=response_metadata,
                content=f"tool_response:{tool_name}(proxy:{server_name})",
                node_did=self.did,
                target_did=sender_did,
                private_key_path=str(self.private_key_path),
            )
        except Exception as e:
            logger.error("Failed to append hop: %s", e)

        return JSONResponse({
            "result": result_str,
            "tool_name": tool_name,
            "tool_did": self.did,
            "message_type": "tool_response",
            "metadata": response_metadata,
            "proxied_from": server_name,
        })

    async def _handle_record(self, body: dict) -> JSONResponse:
        metadata = body.get("metadata", {})
        node_msg_data = metadata.get("NodeMessage")
        if node_msg_data:
            try:
                node_message = NodeMessage.from_dict(node_msg_data)
                self._tracer.save_node_message(node_message)
            except Exception as e:
                logger.warning("Failed to save NodeMessage: %s", e)
        return JSONResponse({"status": "Record saved"})

    # ------------------------------------------------------------------
    # ad.json
    # ------------------------------------------------------------------

    def _build_ad(self) -> ToolAd:
        attp_endpoint = f"http://{self.host}:{self.port}{self.attp_prefix}"
        if self.host == "0.0.0.0":
            attp_endpoint = f"http://localhost:{self.port}{self.attp_prefix}"

        # 收集所有远程工具
        all_tools = []
        for server_name, tools in self._remote_tools.items():
            all_tools.extend(tools)

        return ToolAd(
            did=self.did,
            name=self.name,
            description=self.description,
            attp_endpoint=attp_endpoint,
            mcp_tools=all_tools,
        )

    def generate_ad(self, output_path: str | None = None) -> ToolAd:
        ad = self._build_ad()
        path = Path(output_path) if output_path else self._ad_output_path
        ad.save_to_file(path)
        logger.info("Generated ad.json at %s", path)
        return ad

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动代理：先发现远程工具，再启动 ATTP 服务。"""
        logger.info("Discovering remote MCP tools...")
        await self.discover_remote_tools()

        total_tools = sum(len(t) for t in self._remote_tools.values())
        logger.info("Discovered %d tools from %d servers", total_tools, len(self._remote_tools))

        self.generate_ad()

        config = uvicorn.Config(
            self._app, host=self.host, port=self.port, log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(config)

        async def _run():
            await self._uvicorn_server.serve()

        self._serve_task = asyncio.create_task(_run())
        logger.info(
            "MCPProxyToolNode '%s' started at %s:%d (DID: %s, %d remote tools)",
            self.name, self.host, self.port, self.did, total_tools,
        )

    async def stop(self) -> None:
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except asyncio.CancelledError:
                    pass
        logger.info("MCPProxyToolNode '%s' stopped", self.name)