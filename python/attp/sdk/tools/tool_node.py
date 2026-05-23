"""ATTPToolNode — 将自定义工具函数包装为 ATTP 工具节点。

使用方式：
    from attp.sdk.tools import ATTPToolNode

    node = ATTPToolNode(
        did="did:wba:tool-server.local:my-tool",
        name="my-tool-server",
        private_key_path="key.pem",
        port=9000,
    )

    @node.tool("search", "搜索知识库", {"type": "object", "properties": {...}})
    async def search(query: str, limit: int = 10):
        return {"results": [...]}

    await node.start()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Awaitable

from attp.sdk.tools.mixin import ToolNodeMixin
from attp.sdk.tools.handler import ToolHandler
from attp.sdk.tools.tool_ad import ToolAd

import logging

logger = logging.getLogger("attp.sdk.tools.tool_node")


class ATTPToolNode(ToolNodeMixin):
    """ATTP 工具节点 — 将自定义工具函数包装为 ATTP 网络中的工具节点。"""

    def __init__(
        self,
        did: str,
        name: str,
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

        self._handlers: dict[str, ToolHandler] = {}

        self._init_common(
            did=did, name=name, description=description,
            host=host, port=port, private_key_path=private_key_path,
            attp_prefix=attp_prefix, db_path=db_path,
            ad_output_path=ad_output_path,
            app_title=f"ATTP Tool Node: {name}",
        )

    # ------------------------------------------------------------------
    # 工具注册（装饰器 + 方法）
    # ------------------------------------------------------------------

    def tool(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
    ) -> Callable:
        """装饰器：注册一个工具处理器。"""
        def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            self.register_handler(ToolHandler(
                name=name, description=description,
                input_schema=input_schema, handler=func,
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
    # ToolNodeMixin 抽象方法实现
    # ------------------------------------------------------------------

    async def _execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, int]:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"Tool not found: {tool_name}", 404
        try:
            result = await handler(**arguments)
            result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
            return result_str, 200
        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return f"Tool execution failed: {str(e)}", 500

    def _build_ad(self) -> ToolAd:
        attp_endpoint = f"http://{self.host}:{self.port}{self.attp_prefix}"
        if self.host == "0.0.0.0":
            attp_endpoint = f"http://localhost:{self.port}{self.attp_prefix}"
        return ToolAd(
            did=self.did, name=self.name, description=self.description,
            attp_endpoint=attp_endpoint,
            mcp_tools=[h.to_mcp_tool_dict() for h in self._handlers.values()],
        )