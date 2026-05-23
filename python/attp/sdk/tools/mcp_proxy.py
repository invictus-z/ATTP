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

import json
from pathlib import Path
from typing import Any

import aiohttp

from attp.sdk.tools.mixin import ToolNodeMixin
from attp.sdk.tools.tool_ad import ToolAd

import logging

logger = logging.getLogger("attp.sdk.tools.mcp_proxy")


class MCPProxyToolNode(ToolNodeMixin):
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
        config: dict[str, Any],
        private_key_path: str | None = None,
        host: str = "0.0.0.0",
        port: int = 9000,
        description: str = "",
        db_path: str = "tool_node_traces.db",
        ad_output_path: str | None = None,
        attp_prefix: str = "/attp",
    ):
        if private_key_path is None:
            private_key_path = str(Path.home() / ".attp" / "tools" / name / "did" / "key-1_private.pem")

        self._config = config

        # 远程工具缓存: server_name -> list of tool dicts
        self._remote_tools: dict[str, list[dict[str, Any]]] = {}
        # 扁平化工具索引: tool_name -> (server_name, server_config)
        self._tool_index: dict[str, tuple[str, dict[str, Any]]] = {}

        self._init_common(
            did=did, name=name, description=description,
            host=host, port=port, private_key_path=private_key_path,
            attp_prefix=attp_prefix, db_path=db_path,
            ad_output_path=ad_output_path,
            app_title=f"ATTP Tool Proxy: {name}",
        )

    # ------------------------------------------------------------------
    # ToolNodeMixin 抽象方法实现
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, int]:
        tool_entry = self._tool_index.get(tool_name)
        if not tool_entry:
            return f"Tool not found: {tool_name}", 404

        server_name, server_config = tool_entry
        try:
            result_str = await self._call_remote_tool(server_config, tool_name, arguments)
            return result_str, 200
        except Exception as e:
            logger.exception("Remote MCP call failed: %s/%s", server_name, tool_name)
            return f"Remote tool execution failed: {str(e)}", 502

    def _build_ad(self) -> ToolAd:
        attp_endpoint = f"http://{self.host}:{self.port}{self.attp_prefix}"
        if self.host == "0.0.0.0":
            attp_endpoint = f"http://localhost:{self.port}{self.attp_prefix}"

        all_tools = []
        for tools in self._remote_tools.values():
            all_tools.extend(tools)

        return ToolAd(
            did=self.did, name=self.name, description=self.description,
            attp_endpoint=attp_endpoint,
            mcp_tools=all_tools,
        )

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
        """从远程 MCP 服务获取工具列表。"""
        url = server_config.get("url", "")
        headers = server_config.get("headers", {})

        if not url:
            raise ValueError(f"Server '{server_name}' missing 'url'")

        request_headers = {"Content-Type": "application/json", **headers}

        async with aiohttp.ClientSession() as session:
            # 1. Initialize
            init_payload = {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": f"attp-proxy-{self.name}", "version": "0.1.0"},
                },
            }
            async with session.post(
                url, json=init_payload, headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Initialize failed: HTTP {resp.status}: {text}")

            # 2. Initialized notification
            async with session.post(
                url, json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=request_headers, timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                pass

            # 3. List tools
            async with session.post(
                url, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=request_headers, timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"tools/list failed: HTTP {resp.status}: {text}")
                tools_result = await resp.json()

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
        self, server_config: dict[str, Any], tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """通过 MCP 协议调用远程工具。"""
        url = server_config.get("url", "")
        headers = server_config.get("headers", {})
        request_headers = {"Content-Type": "application/json", **headers}

        call_payload = {
            "jsonrpc": "2.0", "id": 10, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
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
    # Lifecycle（覆盖 Mixin 以加入服务发现）
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动代理：先发现远程工具，再启动 ATTP 服务。"""
        logger.info("Discovering remote MCP tools...")
        await self.discover_remote_tools()

        total_tools = sum(len(t) for t in self._remote_tools.values())
        logger.info("Discovered %d tools from %d servers", total_tools, len(self._remote_tools))

        # 调用 Mixin 的 start()
        await super().start()