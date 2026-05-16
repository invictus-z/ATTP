""" ATTP 服务端 — 处理 agent_request 消息。"""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import aiohttp
import uvicorn
from fastapi import FastAPI
from anp.openanp import anp_agent, interface, AgentConfig
from typing import TYPE_CHECKING

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG
from attp.core.message.event import NodeMessage, BackMessage

logger = get_logger("Server")

from attp.core.sessions.app import AppSessionManager
if TYPE_CHECKING:
    from attp.app.config.config import ATTPServerConfig
    from attp.core.tracer import MessageTracer


class ATTPServer:
    """ ATTP 服务端实现 — 仅接收和处理 agent_request 消息。"""

    def __init__(
        self,
        agent_did: str,
        server_config: ATTPServerConfig,
        session_manager: AppSessionManager,
        web_callback = None,
        attp_channel_callback = None,
        tracer: MessageTracer | None = None,
    ):
        self.session_manager = session_manager
        self._web_callback = web_callback
        self._attp_channel_callback = attp_channel_callback
        self._tracer = tracer
        self._running = False
        self._uvicorn_server = None
        self._serve_task = None

        self._apply_config(agent_did, server_config)

        # Create ATTP agent and FastAPI app
        self.agent_cls = self._create_agent()
        self.app = FastAPI()
        self.app.include_router(self.agent_cls.router())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_config(self, agent_did: str, server_config: ATTPServerConfig) -> None:
        """Update instance attributes from config (shared by __init__ and reload)."""
        self.agent_did = agent_did
        self.server_host = server_config.server_host
        self.server_port = server_config.server_port
        self.name = server_config.name
        self.prefix = server_config.prefix
        self.description = server_config.description
        self.private_key_path = Path(server_config.private_key_path).expanduser()
        self.public_key_path = Path(server_config.public_key_path).expanduser()

    def _create_agent(self):
        """Create the ATTP agent class dynamically."""

        # 通过闭包捕获实例属性，供 Agent 内部方法使用
        session_manager = self.session_manager
        web_callback = self._web_callback
        attp_channel_callback = self._attp_channel_callback
        tracer_ref = self._tracer
        private_key_path_ref = self.private_key_path
        agent_did_ref = self.agent_did

        async def _send_proof_callback(
            node_msg: NodeMessage,
            agent_did: str,
            tracer_ref,
            private_key_path: str | None,
        ):
            """Phase 1 回传：向发送方的协议节点发送接收确认。"""
            if not (tracer_ref and private_key_path):
                return

            try:
                private_key = tracer_ref._key_store.load_private_key(private_key_path)

                back_msg = BackMessage(
                    protocol_url=node_msg.protocol_url,
                    node_did=agent_did,
                    nonce=node_msg.nonce,
                    sig_identity="",
                    recorded_hop=node_msg.recorded_hop,
                )
                back_msg.sign_identity(private_key)

                async with aiohttp.ClientSession() as http:
                    async with http.post(
                        f"{node_msg.protocol_url}/record",
                        json=back_msg.to_dict(),
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            logger.debug(
                                "Phase 1 callback sent to {}", node_msg.protocol_url,
                            )
                        else:
                            logger.warning(
                                "Phase 1 callback: protocol node returned HTTP {}",
                                resp.status,
                            )
            except Exception as e:
                logger.warning("Failed to send Phase 1 callback: {}", e)

        @anp_agent(AgentConfig(
            name=self.name,
            did=self.agent_did,
            prefix=self.prefix,
            description=self.description,
        ))
        class Agent:

            @interface
            async def health(self) -> str:
                """健康检查端点，返回 'ok' 表示服务正常。"""
                return "ok"

            @interface
            async def receive_message(
                self,
                sender_did: str,
                content: str,
                message_type: str,
                metadata: dict | None = None,
            ) -> str:
                """接收来自其他 Agent 的 ATTP 消息。

                仅处理 agent_request 类型。record 类型由 ProtocolNode DataPort 处理。

                Args:
                    sender_did: 发送者 DID
                    content: 消息内容
                    message_type: 消息类型
                    metadata: 附加元数据

                Returns:
                    处理结果
                """
                if message_type == "agent_request":
                    try:
                        # 解析 NodeMessage
                        node_msg_data = (metadata or {}).get("NodeMessage")
                        if not node_msg_data:
                            return "Error: Missing NodeMessage in metadata"
                        node_msg = NodeMessage.from_dict(node_msg_data)

                        session_id = node_msg.recorded_hop.session_id

                        # Store trace metadata
                        if session_id and session_manager:
                            session = session_manager.get_or_create(session_id)
                            session.set_trace_metadata({
                                "Hop": {
                                    "node_did": node_msg.recorded_hop.sender_did,
                                    "target_did": node_msg.recorded_hop.target_did,
                                    "Content": node_msg.recorded_hop.content,
                                    "Timestamp": node_msg.recorded_hop.timestamp,
                                    "Hop_Count": node_msg.recorded_hop.hop_count,
                                    "Signature": node_msg.recorded_hop.sig_content,
                                },
                                "Session_ID": session_id,
                                "Protocol_Node_Address": node_msg.protocol_url,
                                "nonce": node_msg.nonce,
                            })
                            session_manager.save(session)
                            logger.debug(
                                "Session stored/updated: id={}, sender={}",
                                session_id, node_msg.recorded_hop.sender_did,
                            )
                        if attp_channel_callback:
                            await attp_channel_callback(
                                sender=node_msg.recorded_hop.sender_did,
                                chat_id=session_id,
                                content=node_msg.recorded_hop.content,
                                media=[],
                            )

                        # Notify UI of incoming node message
                        if web_callback:
                            await web_callback(node_msg.recorded_hop.content, {
                                "is_node_message": True,
                                "direction": "in",
                                "other_did": node_msg.recorded_hop.sender_did,
                                "Session_ID": session_id,
                            })

                        # Phase 1 回传：向发送方的协议节点发送接收确认
                        await _send_proof_callback(
                            node_msg=node_msg,
                            agent_did=agent_did_ref,
                            tracer_ref=tracer_ref,
                            private_key_path=str(private_key_path_ref) if private_key_path_ref else None,
                        )

                        return "Message received"
                    except Exception as e:
                        logger.error("Error processing ATTP message: {}", e)
                        return f"Error: {str(e)}"

        return Agent

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the ATTP server (non-blocking)."""
        cfg = uvicorn.Config(
            self.app,
            host=self.server_host,
            port=self.server_port,
            log_level="info",
            log_config=UVICORN_SILENT_LOG_CONFIG,
        )
        self._uvicorn_server = uvicorn.Server(cfg)
        self._serve_task = asyncio.create_task(self._uvicorn_server.serve())
        logger.info("started at {}:{}", self.server_host, self.server_port)
        self._running = True

    async def stop(self):
        """Stop the ATTP server gracefully."""
        self._running = False
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            # Wait for graceful shutdown first (lets uvicorn close sockets properly)
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

    async def reload(self, server_config: ATTPServerConfig, agent_did: str) -> None:
        """Stop → update config → rebuild agent/app → start."""
        await self.stop()
        self._apply_config(agent_did, server_config)

        self.agent_cls = self._create_agent()
        self.app = FastAPI()
        self.app.include_router(self.agent_cls.router())

        # Wait until the port is actually available before starting
        await self._wait_for_port("0.0.0.0", self.server_port, timeout=10.0)
        await self.start()
        logger.info("reloaded on {}:{}", self.server_host, self.server_port)

    @staticmethod
    async def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
        """Poll until the port is available for binding."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((host, port))
                return
            except OSError:
                if asyncio.get_event_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.3)
