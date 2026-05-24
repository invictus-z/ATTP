"""Tool Handler — ATTP 工具节点中单个 MCP 工具的处理器抽象。

开发者通过 ToolHandler 定义每个工具的处理逻辑，ATTPToolNode 自动将其
暴露为 ATTP 端点并写入 ad.json。
"""

from __future__ import annotations

from typing import Any, Callable, Awaitable


class ToolHandler:
    """单个工具的处理器描述。

    使用方式：
        handler = ToolHandler(
            name="search",
            description="搜索知识库",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "返回数量", "default": 10},
                },
                "required": ["query"],
            },
            handler=my_search_func,
        )
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., Awaitable[Any]],
    ):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.handler = handler

    def to_mcp_tool_dict(self) -> dict[str, Any]:
        """序列化为 MCP tool 描述格式（用于 ad.json）。"""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    async def __call__(self, **kwargs) -> Any:
        """调用工具。"""
        return await self.handler(**kwargs)