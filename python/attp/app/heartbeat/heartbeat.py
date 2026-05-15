"""HeartbeatManager — 通用心跳调度器。

通过 HealthChecker 协议实现插件化：
- HeartbeatManager 只负责定时调度
- 具体检查逻辑由各个 Checker 实现（_agent.py, _tool.py 等）
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from attp.app.logging import get_logger

logger = get_logger("Heartbeat")

if TYPE_CHECKING:
    from attp.app.config.config import HeartbeatConfig


# ------------------------------------------------------------------
# HealthChecker 协议
# ------------------------------------------------------------------

@runtime_checkable
class HealthChecker(Protocol):
    """所有健康检查器必须实现此协议。"""

    async def check(self) -> None:
        """执行一轮健康检查。"""
        ...


# ------------------------------------------------------------------
# HeartbeatManager
# ------------------------------------------------------------------

class HeartbeatManager:
    """通用心跳调度器 — 定时调用所有已注册的 HealthChecker。

    使用方式：
        mgr = HeartbeatManager(heartbeat_config)
        mgr.add_checker(agent_checker)
        mgr.add_checker(tool_checker)
        await mgr.start()

    职责：
    - 定时触发所有 checker 的 check() 方法
    - 管理 checker 的注册/移除
    - 生命周期管理（start/stop/reload）
    """

    def __init__(self, heartbeat_config: HeartbeatConfig) -> None:
        self._interval = heartbeat_config.interval      # 心跳间隔（秒）
        self._timeout = heartbeat_config.timeout        # 单次心跳超时（秒）
        self._max_fail = heartbeat_config.max_fail      # 连续失败多少次后踢出
        self._task: asyncio.Task | None = None
        self._checkers: list[HealthChecker] = []

    # ------------------------------------------------------------------
    # Checker 管理
    # ------------------------------------------------------------------

    def add_checker(self, checker: HealthChecker) -> None:
        """注册一个健康检查器。"""
        self._checkers.append(checker)
        logger.info("Registered health checker: {}", type(checker).__name__)

    def remove_checker(self, checker: HealthChecker) -> None:
        """移除一个健康检查器。"""
        self._checkers.remove(checker)
        logger.info("Removed health checker: {}", type(checker).__name__)

    @property
    def checkers(self) -> list[HealthChecker]:
        """返回当前已注册的 checker 列表（只读视图）。"""
        return list(self._checkers)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动后台心跳检测任务。"""
        if self._task is not None and not self._task.done():
            logger.warning("already running")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "started (every {}s, {} checkers)",
            self._interval,
            len(self._checkers),
        )

    async def stop(self) -> None:
        """停止心跳检测任务。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("stopped")

    async def reload(self, heartbeat_config: HeartbeatConfig) -> None:
        """Stop → update parameters → restart。Checkers 保持不变。"""
        await self.stop()
        self._interval = heartbeat_config.interval
        self._timeout = heartbeat_config.timeout
        self._max_fail = heartbeat_config.max_fail
        await self.start()
        logger.info(
            "reloaded (interval={}s, timeout={}s, max_fail={})",
            self._interval, self._timeout, self._max_fail,
        )

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """心跳主循环：定时调用所有 checker。"""
        while True:
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break

            for checker in self._checkers:
                try:
                    await checker.check()
                except Exception as e:
                    logger.error(
                        "Checker {} failed: {}",
                        type(checker).__name__, e,
                    )