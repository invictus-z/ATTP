""" ATTP 服务端 """

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from anp.openanp import anp_agent, interface, AgentConfig
from anp.authentication import DidWbaVerifier, DidWbaVerifierConfig
from typing import TYPE_CHECKING

from attp_channel.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("Server")

from .tracing import tracer
from attp_channel.sessions import SessionManager
if TYPE_CHECKING:
    from attp_channel.config.config import ATTPServerConfig


class ATTPServer:
    """ ATTP 服务端实现 """

    def __init__(
        self,
        agent_did: str,
        server_config: ATTPServerConfig,
        session_manager: SessionManager,
        web_callback=None,
        attp_channel_callback = None
    ):
        self.session_manager = session_manager
        self._web_callback = web_callback
        self._attp_channel_callback = attp_channel_callback
        self._running = False
        self._uvicorn_server = None
        self._serve_task = None

        self._apply_config(agent_did, server_config)

        self.verifier = self._create_did_wba_verifier()

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

    def _create_did_wba_verifier(self) -> DidWbaVerifier:
        """Initialize the DID WBA verifier with the configured keys."""
        with open(self.private_key_path, encoding="utf-8") as f:
            jwt_private_key = f.read()
        with open(self.public_key_path, encoding="utf-8") as f:
            jwt_public_key = f.read()

        config = DidWbaVerifierConfig(
            jwt_private_key=jwt_private_key,
            jwt_public_key=jwt_public_key,
            jwt_algorithm="RS256",
            access_token_expire_minutes=600,
        )
        return DidWbaVerifier(config)

    def _create_agent(self):
        """Create the ATTP agent class dynamically."""

        # 通过闭包捕获实例属性，供 Agent 内部方法使用
        session_manager = self.session_manager
        web_callback = self._web_callback
        attp_channel_callback = self._attp_channel_callback

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
                message_type: str = "agent_request",
                metadata: dict | None = None,
            ) -> str:
                """接收来自其他 Agent 的 ATTP 消息。

                Args:
                    sender_did: 发送者 DID
                    content: 消息内容
                    message_type: 消息类型 (agent_request / agent_response / record)
                    metadata: 附加元数据

                Returns:
                    处理结果
                """
                # 处理 record 类型消息
                if message_type == "record":
                    metadata = metadata or {}
                    record_log = metadata.get("Record_Log")
                    if record_log:
                        success = tracer.save_log_to_db(record_log)
                        if success:
                            logger.info("Record log saved from {}", sender_did)
                            return "Record saved"
                        else:
                            return "Error: Failed to save record"
                    return "Error: No log in record metadata"


                metadata = metadata or {}
                if not tracer.validate_chain(metadata):
                    logger.error(
                        "Security Alert: Message from {} failed "
                        "cryptographic chain validation. Task dropped.",
                        sender_did,
                    )
                    return "REJECTED: Trace validation failed."

                try:
                    session_id = metadata.get("Session_ID")

                    # Store/update full metadata for the session
                    if session_id and session_manager:
                        session = session_manager.get_or_create(session_id)
                        session.update_metadata(metadata)
                        session_manager.save(session)
                        logger.debug(
                            "Session stored/updated: id={}, sender={}, metadata keys={}",
                            session_id, sender_did, list(session.metadata.keys()),
                        )
                    if attp_channel_callback:
                        await attp_channel_callback(
                            sender=sender_did,
                            chat_id=session_id,
                            content=content,
                            media=[],
                        )
                    
                    # Notify UI of incoming node message
                    if web_callback:
                        await web_callback(content, {
                            "is_node_message": True,
                            "direction": "in",
                            "other_did": sender_did,
                            "Session_ID": metadata.get("Session_ID"),
                        })
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
        """Stop → update config → rebuild verifier/agent/app → start."""
        await self.stop()
        self._apply_config(agent_did, server_config)

        self.verifier = self._create_did_wba_verifier()
        self.agent_cls = self._create_agent()
        self.app = FastAPI()
        self.app.include_router(self.agent_cls.router())

        # Wait until the port is actually available before starting
        # Check 0.0.0.0 (superset) since uvicorn may bind to it regardless of config
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
