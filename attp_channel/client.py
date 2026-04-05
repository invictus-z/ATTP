"""ANP client for sending messages to agents and users, using OpenANP SDK."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, Optional

from anp.openanp import RemoteAgent
from anp.authentication import DIDWbaAuthHeader
from loguru import logger

from .tracing import tracer

if TYPE_CHECKING:
    from .config_manager import ANPClientConfig


# Type alias for the UI notification callback
UICallback = Callable[[str, dict], Awaitable[None]]


class ANPClient:
    """Client for sending ANP messages via OpenANP SDK."""

    def __init__(
        self,
        agent_did: str,
        client_config: ANPClientConfig,
        message_bus=None,
        ui_callback: UICallback = None,
    ):
        """Initialize ANP client.

        Args:
            agent_did: The DID of the local agent.
            client_config: ANPClientConfig parsed from anp_config.json.
            message_bus: MessageBus instance (kept for backward compat).
            ui_callback: Direct callback to WebUIChannel.send_to_ui.
        """
        self.agent_did = agent_did
        self.message_bus = message_bus
        self._ui_callback = ui_callback

        # Resolve paths from config
        did_doc_path = str(Path(client_config.did_doc_path).expanduser())
        did_key_path = str(Path(client_config.did_key_path).expanduser())

        self.auth = DIDWbaAuthHeader(
            did_document_path=did_doc_path,
            private_key_path=did_key_path,
        )
        self.registry: list[str] = client_config.node_ads or []

        self._remote_agents: dict[str, RemoteAgent] = {}  # 当前已连接的 agent
        self._registered_agents: dict[str, dict] = {}  # 已注册过的 agent 元信息
        self._failed_urls: set[str] = set()  # 未连接的 URL（待重连）
        # Heartbeat related
        self._heartbeat_interval: int = 60  # 心跳间隔（秒）
        self._heartbeat_timeout: int = 30   # 单次心跳超时（秒）
        self._heartbeat_task: asyncio.Task | None = None
        self._fail_counts: dict[str, int] = {}  # 连续心跳失败计数 {did: count}

    # ------------------------------------------------------------------
    # Agent discovery & caching
    # ------------------------------------------------------------------

    def _record_successful_agent(self, identifier: str, remote: RemoteAgent, ad_url: str):
        """Record a successfully discovered agent to _registered_agents."""
        try:
            self._registered_agents[identifier] = {
                "did": identifier,
                "name": getattr(remote, "name", ""),
                "description": getattr(remote, "description", ""),
                "ad_url": ad_url,
                "capabilities": [],
            }
            logger.info(f"Recorded agent {identifier} to registered agents")
        except Exception as e:
            logger.error(f"Failed to record agent {identifier}: {e}", exc_info=True)

    async def initialize(self):
        """Initialize connections to all agents from the registry.

        Loads all ad.json files and establishes connections to remote agents.
        Stores them in self._remote_agents for future use.
        Failed URLs are stored in _failed_urls for retry later.
        """
        logger.info(f"Initializing ANP client with registry: {self.registry}")
        if not self.registry:
            logger.warning("No registry loaded, skipping agent initialization")
            return

        success_count = 0
        for ad_path in self.registry:
            if ad_path:
                remote = await self._get_remote_agent(ad_path)
                if remote:
                    success_count += 1
                else:
                    self._failed_urls.add(ad_path)
        
        logger.info(f"Initialized {success_count}/{len(self.registry)} remote agents, {len(self._failed_urls)} failed")
        if self._failed_urls:
            logger.info(f"Failed URLs (will retry on heartbeat): {', '.join(self._failed_urls)}")

        self.start_heartbeat()

    async def _get_remote_agent(self, target_ad: str) -> Optional[RemoteAgent]:
        """Discover and cache a remote agent by ad.json URL."""
        try:
            remote = await RemoteAgent.discover(target_ad, self.auth)

            # Read the ad.json from URL to get the identifier
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(target_ad) as response:
                        if response.status == 200:
                            ad_data = await response.json()
                            identifier = ad_data.get("identifier")
                            if identifier:
                                self._remote_agents[identifier] = remote
                                logger.info(f"Successfully discovered agent {identifier} at {target_ad}")

                                self._record_successful_agent(identifier, remote, target_ad)

                                # 重置失败计数（如果是重连回来的）
                                self._fail_counts.pop(identifier, None)

                                return remote
                            else:
                                logger.error(f"No 'identifier' found in JSON from {target_ad}")
                                return None
                        else:
                            logger.error(f"HTTP {response.status} from {target_ad}")
                            return None
            except Exception as e:
                logger.error(f"Failed to read identifier from {target_ad}: {e}", exc_info=True)
                return None
        except Exception as e:
            logger.error(f"Failed to discover agent at {target_ad}: {e}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Sending messages
    # ------------------------------------------------------------------

    async def send_to_agent(
        self,
        target_did: str,
        sender_did: str,
        content: str,
        message_type: str = "agent_request",
        metadata: dict = None,
    ) -> str:
        """Send message to another agent via OpenANP SDK.

        Args:
            target_did: Target agent DID
            sender_did: This agent's DID
            content: Message content
            message_type: Message type
            metadata: Optional metadata for extension and security tracing

        Returns:
            Response from target agent
        """
        remote = self._remote_agents.get(target_did)

        # If agent not found, try to reconnect from failed URLs
        if not remote:
            remote = await self._retry_failed_urls(target_did=target_did)
            if not remote:
                return f"Error: Agent {target_did} not found or unreachable"

        metadata = metadata or {}
        try:
            private_key_path = str(self.auth.private_key_path) if getattr(self.auth, "private_key_path", None) else None
            if private_key_path:
                metadata = tracer.append_hop(
                    metadata=metadata,
                    content_snapshot=content[:100],
                    node_did=sender_did,
                    target_did=target_did,
                    private_key_path=private_key_path,
                )
        except Exception as e:
            logger.error(f"Failed to append tracing hop: {e}")
            return f"Error: Tracing hook failed - {str(e)}"

        try:
            # 发送原始消息
            result = await remote.receive_message(
                sender_did=sender_did,
                content=content,
                message_type=message_type,
                metadata=metadata,
            )

            # 向消息最初发出者发送 record 副本
            try:
                origin_did = tracer.get_origin_did(metadata)
                if origin_did and origin_did != sender_did:
                    # 获取最新的 log（即 append_hop 刚添加的）
                    path = metadata.get("Path", [])
                    if path:
                        latest_log = path[-1]["Log"]

                        # 构造 record 消息的 metadata（只包含最新 log）
                        record_metadata = {
                            "Session_ID": metadata.get("Session_ID"),
                            "Record_Log": latest_log,
                        }

                        # 发送 record 类型消息到最初发出者
                        origin_remote = await self._get_remote_agent(origin_did)
                        if origin_remote:
                            await origin_remote.receive_message(
                                sender_did=sender_did,
                                content=content,
                                message_type="record",
                                metadata=record_metadata,
                            )
                            logger.debug(f"Sent record to origin {origin_did}")
            except Exception as e:
                logger.warning("Failed to send record copy: %s", e)

            if self._ui_callback:
                await self._ui_callback(content, {
                    "is_node_message": True,
                    "direction": "out",
                    "other_did": target_did,
                    "Session_ID": metadata.get("Session_ID"),
                })
            

            return result if isinstance(result, str) else str(result)
        except Exception as e:
            logger.error(f"Error sending to agent {target_did}: {e}")
            return f"Error: {str(e)}"

    async def send_to_user(
        self,
        channel: str,
        current_session_id: str,
        content: str,
    ) -> str:
        """Send message to user via MessageBus.

        Args:
            channel: Channel name (e.g., "web_ui")
            current_session_id: Current session ID
            content: Message content

        Returns:
            Status message
        """
        if self._ui_callback:
            await self._ui_callback(content, {"Session_ID": current_session_id})
        return "Message sent to user"

    # ------------------------------------------------------------------
    # Retry failed URLs
    # ------------------------------------------------------------------

    async def _retry_failed_urls(self, target_did: str = None) -> Optional[RemoteAgent]:
        """尝试重新连接失败的 URL。

        Args:
            target_did: 如果指定，只关心该 DID 的 agent 是否重连成功；
                        如果为 None，则尝试所有失败 URL（用于心跳批量重连）。

        Returns:
            如果 target_did 指定且重连成功，返回对应的 RemoteAgent；
            如果 target_did 为 None，返回 None（仅副作用：更新 _remote_agents 和 _failed_urls）。
        """
        if not self._failed_urls:
            return None

        if target_did:
            logger.info(f"Agent {target_did} not found, attempting to reconnect to {len(self._failed_urls)} failed URLs")
        else:
            logger.info(f"[ANP Client Heartbeat] retrying {len(self._failed_urls)} failed URLs...")

        for failed_url in list(self._failed_urls):
            remote = await self._get_remote_agent(failed_url)
            if remote:
                self._failed_urls.discard(failed_url)

                if target_did:
                    if target_did in self._remote_agents:
                        logger.info(f"Successfully reconnected to agent {target_did} from {failed_url}")
                        return self._remote_agents[target_did]
                else:
                    logger.info(f"[ANP Client Heartbeat] successfully reconnected agent from {failed_url}")
                    continue

        return None

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def start_heartbeat(self):
        """启动后台心跳检测任务。"""
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            logger.warning("[ANP Client Heartbeat] already running")
            return
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info(f"[ANP Client Heartbeat] started (every {self._heartbeat_interval}s)")

    def stop_heartbeat(self):
        """停止心跳检测任务。"""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
            logger.info("[ANP Client Heartbeat] stopped")

    async def _heartbeat_loop(self):
        """心跳主循环：重连失败 URL + 检测已连接 agent。"""
        while True:
            try:
                await asyncio.sleep(self._heartbeat_interval)
            except asyncio.CancelledError:
                break

            # 1. 重连失败的 URL
            await self._retry_failed_urls(target_did=None)

            # 2. 对已连接的远程 agent 执行心跳检测
            if not self._remote_agents:
                continue

            logger.debug(f"[ANP Client Heartbeat] checking {len(self._remote_agents)} remote agents...")
            for did, remote in list(self._remote_agents.items()):
                await self._check_agent_heartbeat(did, remote)

    async def _check_agent_heartbeat(self, did: str, remote: RemoteAgent):
        """对单个 agent 执行心跳检测，连续失败 3 次则移回 _failed_urls。"""
        try:
            result = await asyncio.wait_for(
                remote.health(),
                timeout=self._heartbeat_timeout,
            )
            if result == "ok":
                self._fail_counts.pop(did, None)
                logger.debug(f"[ANP Client Heartbeat] agent {did} is healthy")
            else:
                self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
                logger.warning(
                    f"[ANP Client Heartbeat] agent {did} returned unexpected response: "
                    f"{result} (fail_count={self._fail_counts[did]})"
                )
                if self._fail_counts[did] >= 3:
                    self._evict_agent(did)
        except asyncio.TimeoutError:
            self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
            logger.warning(
                f"[ANP Client Heartbeat] agent {did} timed out ({self._heartbeat_timeout}s) "
                f"(fail_count={self._fail_counts[did]})"
            )
            if self._fail_counts[did] >= 3:
                self._evict_agent(did)
        except Exception as e:
            self._fail_counts[did] = self._fail_counts.get(did, 0) + 1
            logger.warning(
                f"[ANP Client Heartbeat] agent {did} error: {e} "
                f"(fail_count={self._fail_counts[did]})"
            )
            if self._fail_counts[did] >= 3:
                self._evict_agent(did)

    def _evict_agent(self, did: str):
        """将 agent 从 _remote_agents 中移除，其 ad_url 加回 _failed_urls。"""
        self._remote_agents.pop(did, None)
        self._fail_counts.pop(did, None)

        ad_url = self._registered_agents.get(did, {}).get("ad_url")
        if ad_url:
            self._failed_urls.add(ad_url)
            logger.warning(
                f"[ANP Client Heartbeat] agent {did} evicted, "
                f"ad_url={ad_url} added back to failed_urls"
            )
        else:
            logger.warning(
                f"[ANP Client Heartbeat] agent {did} evicted, "
                f"but no ad_url found in registered_agents"
            )