"""ANP server for receiving messages from other agents, using OpenANP SDK."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from anp.openanp import anp_agent, interface, AgentConfig
from anp.authentication import DidWbaVerifier, DidWbaVerifierConfig
from loguru import logger
from typing import TYPE_CHECKING

from nanobot.anp.tracing import tracer

if TYPE_CHECKING:
    from nanobot.anp.config_manager import ANPServerConfig

# MessageBus reference, set at startup
_message_bus = None


def set_message_bus(bus):
    """Set the global message bus reference."""
    global _message_bus
    _message_bus = bus


class ANPServer:
    """ANP server wrapping the OpenANP agent."""

    def __init__(
        self,
        agent_did: str,
        server_config: ANPServerConfig,
        message_bus=None,
    ):
        self.agent_did = agent_did
        self.server_port = server_config.server_port
        self.name = server_config.name
        self.prefix = server_config.prefix
        self.description = server_config.description
        self.private_key_path = Path(server_config.private_key_path).expanduser()
        self.public_key_path = Path(server_config.public_key_path).expanduser()

        self.message_bus = message_bus
        set_message_bus(message_bus)

        self.verifier = self._create_did_wba_verifier()

        # Create ANP agent and FastAPI app
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

        server_did = self.agent_did  # capture for closure

        @anp_agent(AgentConfig(
            name=self.name,
            did=self.agent_did,
            prefix=self.prefix,
            description=self.description,
        ))
        class Agent:
            did = server_did

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
                metadata: dict = None,
            ) -> str:
                """接收来自其他 Agent 的 ANP 消息。

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

                if _message_bus is None:
                    return "Error: MessageBus not initialized"

                metadata = metadata or {}
                if not tracer.validate_chain(metadata):
                    logger.error(
                        f"Security Alert: Message from {sender_did} failed "
                        f"cryptographic chain validation. Task dropped."
                    )
                    return "REJECTED: Trace validation failed."

                try:
                    from nanobot.bus.events import InboundMessage, OutboundMessage

                    inbound = InboundMessage(
                        channel="anp",
                        sender_id=sender_did,
                        chat_id=server_did,
                        content=content,
                        metadata=metadata,
                    )
                    await _message_bus.publish_inbound(inbound)

                    # Notify UI of incoming node message
                    await _message_bus.publish_outbound(OutboundMessage(
                        channel="web_ui",
                        content=content,
                        metadata={
                            "is_node_message": True,
                            "direction": "in",
                            "other_did": sender_did,
                            "Session_ID": metadata.get("Session_ID"),
                        },
                    ))
                    return "Message received"
                except Exception as e:
                    logger.error("Error processing ANP message: %s", e)
                    return f"Error: {str(e)}"

        return Agent

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the ANP server."""
        cfg = uvicorn.Config(
            self.app,
            host="0.0.0.0",
            port=self.server_port,
            log_level="info",
        )
        server = uvicorn.Server(cfg)
        await server.serve()