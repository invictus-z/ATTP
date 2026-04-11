""" ATTP 服务端 """

from __future__ import annotations

import asyncio
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from anp.openanp import anp_agent, interface, AgentConfig
from anp.authentication import DidWbaVerifier, DidWbaVerifierConfig
from loguru import logger
from typing import TYPE_CHECKING

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
        self.agent_did = agent_did
        self.server_port = server_config.server_port
        self.session_manager = session_manager
        self.name = server_config.name
        self.prefix = server_config.prefix
        self.description = server_config.description
        self.private_key_path = Path(server_config.private_key_path).expanduser()
        self.public_key_path = Path(server_config.public_key_path).expanduser()
        self._web_callback = web_callback
        self._attp_channel_callback = attp_channel_callback
        self._running = False
        self._uvicorn_server = None
        self._serve_task = None

        self.verifier = self._create_did_wba_verifier()

        # Create ATTP agent and FastAPI app
        self.agent_cls = self._create_agent()
        self.app = FastAPI()
        self.app.include_router(self.agent_cls.router())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        """Create the ANP agent class dynamically."""

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
                            logger.info(f"Record log saved from {sender_did}")
                            return "Record saved"
                        else:
                            return "Error: Failed to save record"
                    return "Error: No log in record metadata"


                metadata = metadata or {}
                if not tracer.validate_chain(metadata):
                    logger.error(
                        f"Security Alert: Message from {sender_did} failed "
                        f"cryptographic chain validation. Task dropped."
                    )
                    return "REJECTED: Trace validation failed."

                try:
                    session_id = metadata.get("Session_ID")

                    # Store/update full metadata for the session
                    if session_id and session_manager:
                        session = session_manager.get_or_create(session_id)
                        session.update_metadata(metadata)
                        session.set_metadata("sender_did", sender_did)
                        session.set_metadata("message_type", message_type)
                        session_manager.save(session)
                        logger.debug(
                            "Session stored/updated: id={}, sender={}, "
                            "metadata keys={}",
                            session_id, sender_did,
                            list(session.metadata.keys()),
                        )
                    if attp_channel_callback:
                        await attp_channel_callback(
                            sender_id=sender_did,
                            chat_id=session_id,
                            content=content
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
                    logger.error("Error processing ATTP message: %s", e)
                    return f"Error: {str(e)}"

        return Agent

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the ATTP server (non-blocking)."""
        cfg = uvicorn.Config(
            self.app,
            host="0.0.0.0",
            port=self.server_port,
            log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(cfg)
        self._serve_task = asyncio.create_task(self._uvicorn_server.serve())
        self._running = True

    async def stop(self):
        """Stop the ATTP server gracefully."""
        self._running = False
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            self._serve_task.cancel()
            try:
                await self._serve_task
            except asyncio.CancelledError:
                pass