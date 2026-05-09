""" ATTP 客户端 """

from __future__ import annotations

import time
import aiohttp
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anp.openanp import RemoteAgent
from anp.authentication import DIDWbaAuthHeader
from attp.app.logging import get_logger

logger = get_logger("Client")

from attp.core.sessions import SessionManager

if TYPE_CHECKING:
    from attp.app.config.config import ATTPClientConfig
    from attp.core.tracer import MessageTracer

class ATTPClient:
    """ATTP 客户端实现"""

    def __init__(
        self,
        agent_did: str,
        client_config: ATTPClientConfig,
        session_manager: SessionManager | None = None,
        web_callback = None,
        tracer: MessageTracer = None,
    ):
        self._tracer = tracer
        self.agent_did = agent_did
        self._session_manager = session_manager or SessionManager()
        self._web_callback = web_callback
        self._running = False

        # Resolve paths from config
        did_doc_path = str(Path(client_config.did_doc_path).expanduser())
        did_key_path = str(Path(client_config.did_key_path).expanduser())

        self.auth = DIDWbaAuthHeader(
            did_document_path=did_doc_path,
            private_key_path=did_key_path,
        )
        self.registry: list[str] = client_config.node_ads or []

        self.remote_agents: dict[str, RemoteAgent] = {}  # 当前已连接的 agent
        self.registered_agents: dict[str, dict] = {}  # 已注册过的 agent 元信息
        self.failed_urls: set[str] = set()  # 未连接的 URL（待重连）

    async def start(self):
        await self.initialize()
        self._running = True

    async def stop(self):
        self._running = False

    async def reload(self, client_config: ATTPClientConfig, agent_did: str) -> None:
        """Reload client with new config: stop → update auth/registry → reinitialize."""
        self._running = False
        self.agent_did = agent_did

        # Resolve new paths
        did_doc_path = str(Path(client_config.did_doc_path).expanduser())
        did_key_path = str(Path(client_config.did_key_path).expanduser())
        self.auth = DIDWbaAuthHeader(
            did_document_path=did_doc_path,
            private_key_path=did_key_path,
        )
        self.registry = client_config.node_ads or []

        # Clear existing connections
        self.remote_agents.clear()
        self.registered_agents.clear()
        self.failed_urls.clear()

        # Reinitialize
        await self.initialize()
        self._running = True
        logger.info("reloaded with {} agents, {} failed", len(self.remote_agents), len(self.failed_urls))

    # ------------------------------------------------------------------
    # Agent discovery & caching
    # ------------------------------------------------------------------

    async def initialize(self):
        """Initialize connections to all agents from the registry.

        Loads all ad.json files and establishes connections to remote agents.
        Stores them in self._remote_agents for future use.
        Failed URLs are stored in _failed_urls for retry later.
        """
        logger.info("Initializing with registry: {}", self.registry)
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
                    self.failed_urls.add(ad_path)

        logger.info("Initialized {}/{} remote agents, {} failed", success_count, len(self.registry), len(self.failed_urls))
        if self.failed_urls:
            logger.info("Failed URLs (will retry on heartbeat): {}", ", ".join(self.failed_urls))

    async def _get_remote_agent(self, target_ad: str) -> RemoteAgent | None:
        """Discover and cache a remote agent by ad.json URL."""
        try:
            remote = await RemoteAgent.discover(target_ad, self.auth)

            # Read the ad.json from URL to get the identifier
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(target_ad) as response:
                        if response.status == 200:
                            ad_data = await response.json()
                            identifier = ad_data.get("identifier")
                            if identifier:
                                self.remote_agents[identifier] = remote
                                logger.info("Successfully discovered agent {} at {}", identifier, target_ad)

                                self.registered_agents[identifier] = {
                                    "did": identifier,
                                    "name": getattr(remote, "name", ""),
                                    "description": getattr(remote, "description", ""),
                                    "ad_url": target_ad,
                                    "capabilities": [],
                                }

                                return remote
                            else:
                                logger.error("No 'identifier' found in JSON from {}", target_ad)
                                return None
                        else:
                            logger.error("HTTP {} from {}", response.status, target_ad)
                            return None
            except Exception as e:
                logger.error("Failed to read identifier from {}: {}", target_ad, e, exc_info=True)
                return None
        except Exception as e:
            logger.error("Failed to discover agent at {}: {}", target_ad, e, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Unified message entry-point
    # ------------------------------------------------------------------

    async def send_message(self, target: str, content: str, chat_id: str) -> str:
        """Unified entry-point for sending messages.

        Routes to user or agent based on target prefix, manages session
        and trace metadata internally.

        Args:
            target: "user:web_ui" or agent DID ("did:wba:...").
            content: Message body.
            chat_id: Session identifier for routing and trace tracking.

        Returns:
            Result string (success message or error description).
        """
        if not target or not content or not chat_id:
            return "Error: target, content and chat_id are all required."

        session = self._session_manager.get_or_create(chat_id)

        # ----- send to user -----
        if target.startswith("user:"):
            return await self.send_to_user(
                current_session_id=chat_id,
                content=content,
            )

        # ----- send to agent -----
        if target.startswith("did:"):
            trace_metadata = session.get_trace_metadata()
            metadata: dict[str, Any] = {"Session_ID": chat_id}
            if trace_metadata:
                metadata.update(trace_metadata)

            result = await self.send_to_agent(
                target_did=target,
                sender_did=self.agent_did,
                content=content,
                message_type="agent_request",
                metadata=metadata,
            )

            # Persist updated trace back to session
            if "Hop" in metadata:
                session.set_trace_metadata({
                    "Hop": metadata["Hop"],
                    "Session_ID": metadata.get("Session_ID"),
                    "Protocol_Node_Address": metadata.get("Protocol_Node_Address"),
                })
                self._session_manager.save(session)

            return result if isinstance(result, str) else str(result)

        return "Error: Invalid target format. Use 'user:web_ui' or 'did:wba:...'"

    # ------------------------------------------------------------------
    # Sending messages
    # ------------------------------------------------------------------

    async def send_to_agent(
        self,
        target_did: str,
        sender_did: str,
        content: str,
        message_type: str = "agent_request",
        metadata: dict | None = None,
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
        remote = self.remote_agents.get(target_did)

        # If agent not found, try to reconnect from failed URLs
        if not remote:
            remote = await self.retry_failed_urls(target_did=target_did)
            if not remote:
                return f"Error: Agent {target_did} not found or unreachable"

        metadata = metadata or {}
        prev_hop = metadata.get("Hop")  # append_hop 会覆盖 Hop
        try:
            private_key_path = str(self.auth.private_key_path) if getattr(self.auth, "private_key_path", None) else None
            if private_key_path:
                metadata = self._tracer.append_hop(
                    metadata=metadata,
                    content=content,
                    node_did=sender_did,
                    target_did=target_did,
                    private_key_path=private_key_path,
                )
        except Exception as e:
            logger.error("Failed to append tracing hop: {}", e)
            return f"Error: Tracing hook failed - {str(e)}"

        # Record field A2A: Agent→Agent
        try:
            # 发送原始消息
            result = await remote.receive_message(
                sender_did=sender_did,
                content=content,
                message_type=message_type,
                metadata=metadata,
            )

            # 向协议节点发送 record 副本
            try:
                protocol_node_url = metadata.get("Protocol_Node_Address")
                if protocol_node_url:
                    record_log = metadata.get("Hop")
                    if record_log:
                        record_metadata = {
                            "Session_ID": metadata.get("Session_ID"),
                            "Record_Log": record_log,
                            "PrevHop": prev_hop,
                            "Protocol_Node_Address": protocol_node_url,
                            "BehaviorEntry": {
                                "field_type": "A2A",
                                "content": content,
                                "target": target_did,
                                "timestamp": time.time(),
                                "node_did": sender_did,
                                "hop_count": metadata["Hop"]["Hop_Count"],
                            },
                        }

                        async with aiohttp.ClientSession() as http_session:
                            async with http_session.post(
                                f"{protocol_node_url}/record",
                                json={
                                    "sender_did": sender_did,
                                    "content": content,
                                    "metadata": record_metadata,
                                },
                                timeout=aiohttp.ClientTimeout(total=10),
                            ) as resp:
                                if resp.status == 200:
                                    logger.debug("Record sent to protocol node at {}", protocol_node_url)
                                else:
                                    logger.warning("Protocol node returned HTTP {}", resp.status)
            except Exception as e:
                logger.warning("Failed to send record to protocol node: {}", e)

            if self._web_callback:
                await self._web_callback(content, {
                    "is_node_message": True,
                    "direction": "out",
                    "other_did": target_did,
                    "Session_ID": metadata.get("Session_ID"),
                })


            return result if isinstance(result, str) else str(result)
        except Exception as e:
            logger.error("Error sending to agent {}: {}", target_did, e)
            return f"Error: {str(e)}"

    async def send_to_user(
        self,
        current_session_id: str,
        content: str,
    ) -> str:
        """Send message to user via websocket.

        Args:
            channel: Channel name (e.g., "web_ui")
            current_session_id: Current session ID
            content: Message content

        Returns:
            Status message
        """
        if self._web_callback:
            await self._web_callback(content, {"Session_ID": current_session_id})
        return "Message sent to user"

    # ------------------------------------------------------------------
    # Retry failed URLs
    # ------------------------------------------------------------------

    async def retry_failed_urls(self, target_did: str = None) -> RemoteAgent | None:
        """尝试重新连接失败的 URL。

        Args:
            target_did: 如果指定，只关心该 DID 的 agent 是否重连成功；
                        如果为 None，则尝试所有失败 URL（用于心跳批量重连）。

        Returns:
            如果 target_did 指定且重连成功，返回对应的 RemoteAgent；
            如果 target_did 为 None，返回 None（仅副作用：更新 _remote_agents 和 _failed_urls）。
        """
        if not self.failed_urls:
            return None

        if target_did:
            logger.info("Agent {} not found, attempting to reconnect to {} failed URLs", target_did, len(self.failed_urls))
        else:
            logger.info("retrying {} failed URLs...", len(self.failed_urls))

        for failed_url in list(self.failed_urls):
            remote = await self._get_remote_agent(failed_url)
            if remote:
                self.failed_urls.discard(failed_url)

                if target_did:
                    if target_did in self.remote_agents:
                        logger.info("Successfully reconnected to agent {} from {}", target_did, failed_url)
                        return self.remote_agents[target_did]
                else:
                    logger.info("successfully reconnected agent from {}", failed_url)

        return None
