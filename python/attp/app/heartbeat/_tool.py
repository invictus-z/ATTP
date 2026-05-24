"""ToolNodeHealthChecker — 工具节点健康检查器。

定时检查已注册的 ATTP 工具节点健康状态：
- 连续失败超过阈值 → 从 MCPToolBridge 注销（动态移除 MCP 工具）
- 恢复成功 → 重新发现并注册（动态添加 MCP 工具）

依赖 MCPToolBridge（待改造完成后接入）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp

from attp.app.logging import get_logger

logger = get_logger("Heartbeat.Tool")

if TYPE_CHECKING:
    from attp.app.tools.mcp_tool_bridge import MCPToolBridge


class ToolNodeHealthChecker:
    """工具节点健康检查器。

    每轮 check() 执行：
    1. 检查所有已注册工具节点的 /health 端点
    2. 连续失败超过阈值 → 调用 tool_bridge.unregister_tool_node()
    3. 尝试重新发现之前失败的工具节点
    """

    def __init__(
        self,
        tool_bridge: MCPToolBridge,
        timeout: int = 90,
        max_fail: int = 3,
    ) -> None:
        self._tool_bridge = tool_bridge
        self._timeout = timeout
        self._max_fail = max_fail
        self._fail_counts: dict[str, int] = {}
        self._failed_nodes: dict[str, str] = {}

    @property
    def timeout(self) -> int:
        return self._timeout

    @timeout.setter
    def timeout(self, value: int) -> None:
        self._timeout = value

    @property
    def max_fail(self) -> int:
        return self._max_fail

    @max_fail.setter
    def max_fail(self, value: int) -> None:
        self._max_fail = value

    async def check(self) -> None:
        """执行一轮工具节点健康检查。"""
        await self._check_tool_nodes()
        await self._retry_failed_nodes()

    async def _check_tool_nodes(self) -> None:
        """检查所有已注册工具节点的健康状态。"""
        tool_nodes = self._tool_bridge.get_tool_nodes()
        if not tool_nodes:
            return

        for did, info in list(tool_nodes.items()):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        f"{info.attp_endpoint}/health",
                        timeout=aiohttp.ClientTimeout(total=self._timeout),
                    ) as resp:
                        if resp.status == 200:
                            self._fail_counts.pop(did, None)
                            logger.debug("tool node {} is healthy", did)
                        else:
                            await self._record_fail(did, info.ad_url)
            except Exception as e:
                logger.debug("tool node {} health check error: {}", did, e)
                await self._record_fail(did, info.ad_url)

    async def _record_fail(self, did: str, ad_url: str) -> None:
        """记录一次失败，超过阈值则 evict。"""
        self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
        count = self._fail_counts[did]

        if count >= self._max_fail:
            await self._evict(did, ad_url)
        else:
            logger.debug(
                "tool node {} failed ({}/{})",
                did, count, self._max_fail,
            )

    async def _evict(self, did: str, ad_url: str) -> None:
        """移除工具节点并记录失败信息用于后续恢复。"""
        logger.debug(
            "tool node {} evicted after {} consecutive failures",
            did, self._max_fail,
        )
        await self._tool_bridge.unregister_tool_node(did)
        self._fail_counts.pop(did, None)
        if ad_url:
            self._failed_nodes[ad_url] = did

    async def _retry_failed_nodes(self) -> None:
        """尝试重新发现之前失败的工具节点。"""
        if not self._failed_nodes:
            return

        for ad_url in list(self._failed_nodes):
            result = await self._tool_bridge.discover_tool_node(ad_url)
            if result:
                old_did = self._failed_nodes.pop(ad_url)
                self._fail_counts.pop(old_did, None)
                logger.info("tool node recovered from {}", ad_url)