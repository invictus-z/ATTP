""" 心跳管理 （目前只维护 ATTP 客户端的连接）"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from anp.openanp import RemoteAgent
from loguru import logger

if TYPE_CHECKING:
    from attp_channel.client import ATTPClient
    from attp_channel.config.config import HeartbeatConfig


class HeartbeatManager:
    """Manages heartbeat checks for all remote agents of an ANPClient.

    Responsibilities:
    - Periodically retry failed URLs to reconnect dropped agents.
    - Periodically health-check currently connected agents.
    - Evict agents that fail consecutively beyond a threshold.
    """

    def __init__(
        self,
        heartbeat_config: HeartbeatConfig,
        attp_client: ATTPClient
    ):
        self._attp_client = attp_client
        self._interval = heartbeat_config.interval      # 心跳间隔（秒）
        self._timeout = heartbeat_config.timeout        # 单次心跳超时（秒）
        self._max_fail = heartbeat_config.max_fail      # 连续失败多少次后踢出
        self._task: asyncio.Task | None = None
        self._fail_counts: dict[str, int] = {}  # 连续心跳失败计数 {did: count}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """启动后台心跳检测任务。"""
        if self._task is not None and not self._task.done():
            logger.warning("[Heartbeat] already running")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(f"[Heartbeat] started (every {self._interval}s)")

    def stop(self):
        """停止心跳检测任务。"""
        if self._task:
            self._task.cancel()
            self._task = None
            logger.info("[Heartbeat] stopped")

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def reset_fail_count(self, did: str):
        """重置指定 agent 的连续失败计数（重连成功时由 client 调用）。"""
        self._fail_counts.pop(did, None)

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self):
        """心跳主循环：重连失败 URL + 检测已连接 agent。"""
        while True:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

            # 1. 重连失败的 URL
            await self._attp_client.retry_failed_urls(target_did=None)

            # 2. 对已连接的远程 agent 执行心跳检测
            remote_agents = self._attp_client.remote_agents
            if not remote_agents:
                continue

            logger.debug(f"[Heartbeat] checking {len(remote_agents)} remote agents...")
            for did, remote in list(remote_agents.items()):
                await self._check(did, remote)

    # ------------------------------------------------------------------
    # Per-agent health check
    # ------------------------------------------------------------------

    async def _check(self, did: str, remote: RemoteAgent):
        """对单个 agent 执行心跳检测，连续失败超过阈值则移回 _failed_urls。"""
        try:
            result = await asyncio.wait_for(
                remote.health(),
                timeout=self._timeout,
            )
            if result == "ok":
                self._fail_counts.pop(did, None)
                logger.debug(f"[Heartbeat] agent {did} is healthy")
            else:
                self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
                logger.warning(
                    f"[Heartbeat] agent {did} returned unexpected response: "
                    f"{result} (fail_count={self._fail_counts[did]})"
                )
                if self._fail_counts[did] >= self._max_fail:
                    self._evict(did)
        except asyncio.TimeoutError:
            self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
            logger.warning(
                f"[Heartbeat] agent {did} timed out ({self._timeout}s) "
                f"(fail_count={self._fail_counts[did]})"
            )
            if self._fail_counts[did] >= self._max_fail:
                self._evict(did)
        except Exception as e:
            self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
            logger.warning(
                f"[Heartbeat] agent {did} error: {e} "
                f"(fail_count={self._fail_counts[did]})"
            )
            if self._fail_counts[did] >= self._max_fail:
                self._evict(did)

    def _evict(self, did: str):
        """将 agent 从 _remote_agents 中移除，其 ad_url 加回 _failed_urls。"""
        self._attp_client.remote_agents.pop(did, None)
        self._fail_counts.pop(did, None)

        ad_url = self._attp_client.registered_agents.get(did, {}).get("ad_url")
        if ad_url:
            self._attp_client.failed_urls.add(ad_url)
            logger.warning(
                f"[Heartbeat] agent {did} evicted, "
                f"ad_url={ad_url} added back to failed_urls"
            )
        else:
            logger.warning(
                f"[Heartbeat] agent {did} evicted, "
                f"but no ad_url found in registered_agents"
            )