"""AgentHealthChecker — Agent 健康检查器。

从原 HeartbeatManager 中拆分出来的 Agent 健康检查逻辑：
- 定期健康检查已连接的远程 Agent
- 连续失败超过阈值则 evict
- 定期重连失败的 URL
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from anp.openanp import RemoteAgent
from attp.app.logging import get_logger

logger = get_logger("Heartbeat.Agent")

if TYPE_CHECKING:
    from attp.app.client import ATTPClient


class AgentHealthChecker:
    """Agent 健康检查器 — 检查远程 Agent 连接状态。

    每轮 check() 执行：
    1. 重连失败的 Agent URL
    2. 对已连接的远程 Agent 执行健康检查
    3. 连续失败超过阈值的 Agent 被 evict
    """

    def __init__(
        self,
        attp_client: ATTPClient,
        timeout: int = 90,
        max_fail: int = 3,
    ) -> None:
        self._attp_client = attp_client
        self._timeout = timeout
        self._max_fail = max_fail
        self._fail_counts: dict[str, int] = {}  # 连续心跳失败计数 {did: count}

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

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def reset_fail_count(self, did: str) -> None:
        """重置指定 agent 的连续失败计数（重连成功时由 client 调用）。"""
        self._fail_counts.pop(did, None)

    # ------------------------------------------------------------------
    # HealthChecker 协议实现
    # ------------------------------------------------------------------

    async def check(self) -> None:
        """执行一轮 Agent 健康检查。"""
        # 1. 重连失败的 URL
        await self._attp_client.retry_failed_urls(target_did=None)

        # 2. 对已连接的远程 agent 执行心跳检测
        remote_agents = self._attp_client.remote_agents
        if not remote_agents:
            return

        logger.debug("checking {} remote agents...", len(remote_agents))
        for did, remote in list(remote_agents.items()):
            await self._check_agent(did, remote)

    # ------------------------------------------------------------------
    # Per-agent health check
    # ------------------------------------------------------------------

    async def _check_agent(self, did: str, remote: RemoteAgent) -> None:
        """对单个 agent 执行心跳检测，连续失败超过阈值则移回 _failed_urls。"""
        try:
            result = await asyncio.wait_for(
                remote.health(),
                timeout=self._timeout,
            )
            if result == "ok":
                self._fail_counts.pop(did, None)
                logger.debug("agent {} is healthy", did)
            else:
                self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
                logger.warning(
                    "agent {} returned unexpected response: {} (fail_count={})",
                    did, result, self._fail_counts[did],
                )
                if self._fail_counts[did] >= self._max_fail:
                    self._evict(did)
        except asyncio.TimeoutError:
            self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
            logger.warning(
                "agent {} timed out ({}s) (fail_count={})",
                did, self._timeout, self._fail_counts[did],
            )
            if self._fail_counts[did] >= self._max_fail:
                self._evict(did)
        except Exception as e:
            self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
            logger.warning(
                "agent {} error: {} (fail_count={})",
                did, e, self._fail_counts[did],
            )
            if self._fail_counts[did] >= self._max_fail:
                self._evict(did)

    def _evict(self, did: str) -> None:
        """将 agent 从 _remote_agents 中移除，其 ad_url 加回 _failed_urls。"""
        self._attp_client.remote_agents.pop(did, None)
        self._fail_counts.pop(did, None)

        ad_url = self._attp_client.registered_agents.get(did, {}).get("ad_url")
        if ad_url:
            self._attp_client.failed_urls.add(ad_url)
            logger.warning(
                "agent {} evicted, ad_url={} added back to failed_urls",
                did, ad_url,
            )
        else:
            logger.warning(
                "agent {} evicted, but no ad_url found in registered_agents",
                did,
            )