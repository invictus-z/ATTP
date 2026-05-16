"""MCPToATTPAdapter — 将已有 MCP Server 包装为 ATTP 工具节点。

适用场景：已有 MCP Server 实现（FastMCP 实例），直接暴露为 ATTP 工具节点。

使用方式：
    from mcp.server.fastmcp import FastMCP
    from attp.sdk.tools import MCPToATTPAdapter

    my_mcp = FastMCP("my-service")

    @my_mcp.tool()
    async def search(query: str) -> str:
        return "results..."

    adapter = MCPToATTPAdapter(
        did="did:wba:tool.local:search-service",
        name="search-service",
        mcp_server=my_mcp,
        private_key_path="key.pem",
        port=9000,
    )
    await adapter.start()
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from attp.sdk.tools.mixin import ToolNodeMixin
from attp.sdk.tools.tool_ad import ToolAd

import logging

logger = logging.getLogger("attp.sdk.tools.mcp_adapter")


class MCPToATTPAdapter(ToolNodeMixin):
    """将已有 MCP Server (FastMCP) 包装为 ATTP 工具节点。"""

    def __init__(
        self,
        did: str,
        name: str,
        mcp_server: FastMCP,
        private_key_path: str,
        host: str = "0.0.0.0",
        port: int = 9000,
        description: str = "",
        db_path: str = "tool_node_traces.db",
        ad_output_path: str | None = None,
        attp_prefix: str = "/attp",
    ):
        self.mcp_server = mcp_server

        self._init_common(
            did=did, name=name, description=description,
            host=host, port=port, private_key_path=private_key_path,
            attp_prefix=attp_prefix, db_path=db_path,
            ad_output_path=ad_output_path,
            app_title=f"ATTP Tool Node (MCP Adapter): {name}",
        )

    # ------------------------------------------------------------------
    # ToolNodeMixin 抽象方法实现
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, int]:
        try:
            result = await self.mcp_server.call_tool(tool_name, arguments)
            if isinstance(result, list):
                result_str = "\n".join(
                    getattr(item, 'text', str(item)) for item in result
                )
            else:
                result_str = str(result)
            return result_str, 200
        except Exception as e:
            logger.exception("MCP tool execution failed: %s", tool_name)
            return f"Tool execution failed: {str(e)}", 500

    def _build_ad(self) -> ToolAd:
        attp_endpoint = f"http://{self.host}:{self.port}{self.attp_prefix}"
        if self.host == "0.0.0.0":
            attp_endpoint = f"http://localhost:{self.port}{self.attp_prefix}"
        return ToolAd(
            did=self.did, name=self.name, description=self.description,
            attp_endpoint=attp_endpoint,
            mcp_tools=self._extract_tools_from_mcp(),
        )

    # ------------------------------------------------------------------
    # MCP 工具提取
    # ------------------------------------------------------------------

    def _extract_tools_from_mcp(self) -> list[dict[str, Any]]:
        """从 FastMCP 实例提取工具列表。"""
        tools = []
        try:
            tool_manager = getattr(self.mcp_server, '_tool_manager', None)
            if tool_manager:
                for tool_name, tool_obj in tool_manager._tools.items():
                    tools.append({
                        "name": tool_name,
                        "description": getattr(tool_obj, 'description', '') or '',
                        "inputSchema": getattr(tool_obj, 'parameters', {}) or {},
                    })
        except Exception as e:
            logger.warning("Failed to extract tools from FastMCP: %s", e)
        return tools