"""ATTP SDK Tools — 将 MCP 工具服务包装为 ATTP 工具节点。

核心类：
- ToolNodeMixin: 共用回传逻辑基类（Mixin）
- ATTPToolNode: 自定义工具函数 → ATTP 工具节点
- MCPToATTPAdapter: 已有 FastMCP 实例 → ATTP 工具节点
- MCPProxyToolNode: 远程 MCP 服务 → ATTP 工具节点（代理网关）
- ToolHandler: 单个工具的处理器描述
- ToolAd: 工具节点描述文件（ad.json）构建器
"""

from .mixin import ToolNodeMixin
from .tool_node import ATTPToolNode
from .mcp_adapter import MCPToATTPAdapter
from .mcp_proxy import MCPProxyToolNode
from .handler import ToolHandler
from .tool_ad import ToolAd

__all__ = [
    "ToolNodeMixin",
    "ATTPToolNode",
    "MCPToATTPAdapter",
    "MCPProxyToolNode",
    "ToolHandler",
    "ToolAd",
]