"""Unified ATTP channel: WebSocket UI + ANP agent communication.

For nanobot, both user messages (via WebSocket) and agent messages
(via ANP protocol) enter through the same channel and the same
``_handle_message`` path into the message bus.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

from sessions import SessionManager


class ATTPChannel(BaseChannel):
    """
    Unified channel combining WebSocket UI and ANP agent communication.

    All inbound messages -- whether from a local user via WebSocket or from a
    remote agent via ANP -- flow through ``_handle_message()`` into the same
    message bus.  Outbound routing is unchanged: ``ChannelManager`` dispatches
    ``OutboundMessage(channel="web_ui")`` back to this channel's ``send()``.
    """

    name: str = "web_ui"
    display_name: str = "ATTP Web UI"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        self.host = getattr(config, "host", "127.0.0.1")
        self.port = getattr(config, "port", 8001)
        self._server = None
        self._clients: list[WebSocket] = []
        self._app: FastAPI | None = None

        # External dependencies -- set after construction by startup code
        self.session_manager: SessionManager | None = None
        self.anp_client = None
        self.anp_config_manager = None

        # ANP server state (optional)
        self._agent_did: str | None = None
        self._anp_server_config = None  # ANPServerConfig
        self._verifier = None

    # ------------------------------------------------------------------
    # ANP configuration (call before start())
    # ------------------------------------------------------------------

    def setup_anp(self, agent_did: str, anp_server_config: Any) -> None:
        """Configure ANP server capabilities.

        Args:
            agent_did: DID string for this agent.
            anp_server_config: ANPServerConfig instance.
        """
        self._agent_did = agent_did
        self._anp_server_config = anp_server_config
        self._verifier = self._create_did_wba_verifier()

    # ------------------------------------------------------------------
    # ANP internals (from former ANPServer)
    # ------------------------------------------------------------------

    def _create_did_wba_verifier(self):
        """Initialize the DID WBA verifier with the configured keys."""
        if not self._anp_server_config:
            return None
        try:
            from anp.authentication import DidWbaVerifier, DidWbaVerifierConfig

            cfg = self._anp_server_config
            with open(Path(cfg.private_key_path).expanduser(), encoding="utf-8") as f:
                jwt_private_key = f.read()
            with open(Path(cfg.public_key_path).expanduser(), encoding="utf-8") as f:
                jwt_public_key = f.read()

            config = DidWbaVerifierConfig(
                jwt_private_key=jwt_private_key,
                jwt_public_key=jwt_public_key,
                jwt_algorithm="RS256",
                access_token_expire_minutes=600,
            )
            return DidWbaVerifier(config)
        except Exception as e:
            logger.warning("Failed to create DID WBA verifier: {}", e)
            return None

    def _create_anp_agent(self):
        """Create the ANP agent class dynamically (OpenANP SDK).

        Returns the decorated agent class (with ``router()``), or *None*
        if OpenANP SDK is not available.
        """
        if not self._anp_server_config:
            return None
        try:
            from anp.openanp import anp_agent, interface, AgentConfig
            from attp_channel.tracing import tracer
        except ImportError:
            logger.warning("OpenANP SDK not available, ANP routes disabled")
            return None

        cfg = self._anp_server_config
        channel_ref = self  # capture for closure

        @anp_agent(AgentConfig(
            name=cfg.name,
            did=channel_ref._agent_did,
            prefix=cfg.prefix,
            description=cfg.description,
        ))
        class Agent:
            did = channel_ref._agent_did

            @interface
            async def health(self) -> str:
                """Health check endpoint."""
                return "ok"

            @interface
            async def receive_message(
                self,
                sender_did: str,
                content: str,
                message_type: str = "agent_request",
                metadata: dict = None,
            ) -> str:
                """Receive ANP message from another agent.

                Routes through the unified ``_handle_message`` path so that
                nanobot treats it identically to a WebSocket user message.
                """
                # Handle record-type messages
                if message_type == "record":
                    metadata = metadata or {}
                    record_log = metadata.get("Record_Log")
                    if record_log:
                        success = tracer.save_log_to_db(record_log)
                        if success:
                            logger.info("Record log saved from {}", sender_did)
                            return "Record saved"
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

                    # Store/update Session_Id via SessionManager
                    if session_id and channel_ref.session_manager:
                        session = channel_ref.session_manager.get_or_create(session_id)
                        session.set_metadata("Session_ID", session_id)
                        session.set_metadata("sender_did", sender_did)
                        channel_ref.session_manager.save(session)
                        logger.debug(
                            "Session stored/updated: id={}, sender={}",
                            session_id, sender_did,
                        )

                    # Unified entry: same _handle_message as WebSocket
                    await channel_ref._handle_message(
                        sender_id=sender_did,
                        chat_id=session_id,
                        content=content,
                        metadata={
                            "is_node_message": True,
                            "other_did": sender_did,
                            "Session_ID": session_id,
                        },
                    )

                    # Immediate UI notification (don't wait for agent response)
                    channel_ref._notify_ui_incoming(sender_did, content, metadata)
                    return "Message received"
                except Exception as e:
                    logger.error("Error processing ANP message: {}", e)
                    return f"Error: {e}"

        return Agent

    def _notify_ui_incoming(self, sender_did: str, content: str, metadata: dict) -> None:
        """Fire-and-forget: push incoming ANP message to WebSocket clients."""
        asyncio.ensure_future(self.send_to_ui(content, {
            "is_node_message": True,
            "direction": "in",
            "other_did": sender_did,
            "Session_ID": metadata.get("Session_ID"),
        }))

    # ------------------------------------------------------------------
    # Route registration
    # ------------------------------------------------------------------

    def _register_rest_routes(self) -> None:
        """Register REST API endpoints."""

        @self._app.get("/api/status")
        async def get_status():
            return {
                "status": "active" if self._running else "offline",
                "ws_clients": len(self._clients),
            }

        @self._app.get("/api/nodes")
        async def get_nodes():
            try:
                if not self.anp_client:
                    return {"agents": []}
                online_dids = set(self.anp_client._remote_agents.keys())
                agents = []
                for did, info in self.anp_client._registered_agents.items():
                    agents.append({
                        "did": info.get("did", did),
                        "name": info.get("name", ""),
                        "description": info.get("description", ""),
                        "ad_url": info.get("ad_url", ""),
                        "capabilities": info.get("capabilities", []),
                        "online": did in online_dids,
                    })
                return {"agents": agents}
            except Exception as e:
                logger.error("Error loading nodes: {}", e)
            return {"agents": []}

        @self._app.get("/api/traces/{session_id}")
        async def get_session_trace(session_id: str):
            from datetime import datetime
            import logging as _logging

            _logger = _logging.getLogger(__name__)
            try:
                from attp_channel.tracing import tracer as _tracer

                rows = _tracer.recover_trace(session_id)
                rows.reverse()

                path_list = []
                for row in rows:
                    try:
                        ts = datetime.fromtimestamp(row["timestamp"])
                        time_iso = ts.isoformat() + "Z"
                    except Exception:
                        time_iso = str(row["timestamp"])

                    log_entry = {
                        "node_did": row["node_did"],
                        "target_did": row.get("target_did"),
                        "Entry_Hash": row["entry_hash"],
                        "Prev_Hash": row["prev_hash"],
                        "Session_ID": row["session_id"],
                        "Hop_Count": row["hop_count"],
                        "Content_Snapshot": row["content_snapshot"],
                        "Signature": row["signature"],
                        "Timestamp": time_iso,
                    }
                    if row["hop_count"] == 0:
                        log_entry["Genesis_Hash"] = row["entry_hash"]

                    path_list.append({"Log": log_entry})

                return {
                    "Session_ID": session_id,
                    "Intent_Tag": "Interaction_Trace",
                    "Path": path_list,
                }
            except Exception as e:
                _logger.error("Error recovering trace for %s: %s", session_id, e)
                return {
                    "Session_ID": session_id,
                    "Intent_Tag": "Error",
                    "Path": [],
                }

        @self._app.get("/api/config")
        async def get_config():
            if not self.anp_config_manager:
                return {"error": "ANP is not enabled", "config": None}
            return {
                "config": self.anp_config_manager.anp_config.model_dump(by_alias=True)
            }

        @self._app.put("/api/config")
        async def update_config(request: Request):
            if not self.anp_config_manager:
                return {"error": "ANP is not enabled"}
            try:
                partial = await request.json()
                updated = self.anp_config_manager.update(partial)
                return {
                    "success": True,
                    "config": updated.model_dump(by_alias=True),
                }
            except Exception as e:
                logger.error("Error updating ANP config: {}", e)
                return {"success": False, "error": str(e)}

    def _register_websocket(self) -> None:
        """Register WebSocket endpoint."""

        @self._app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            await ws.accept()
            self._clients.append(ws)
            logger.info("WebUI Client connected: {}", ws.client)
            try:
                while True:
                    data = await ws.receive_text()
                    try:
                        message_data = json.loads(data)
                        content = message_data.get("content", "")
                        msg_type = message_data.get("type", "chat")
                        session_id = (
                            message_data.get("Session_ID")
                            or message_data.get("session_id", "home")
                        )

                        if msg_type == "chat" and content:
                            await self._handle_message(
                                sender_id="user",
                                chat_id=session_id,
                                content=content,
                            )
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON over WebSocket")
            except WebSocketDisconnect:
                logger.info("WebUI Client disconnected: {}", ws.client)
                if ws in self._clients:
                    self._clients.remove(ws)
            except Exception as e:
                logger.error("WebSocket error: {}", e)
                if ws in self._clients:
                    self._clients.remove(ws)

    def _register_anp_routes(self) -> None:
        """Register ANP agent routes if ANP is configured."""
        agent_cls = self._create_anp_agent()
        if agent_cls:
            self._app.include_router(agent_cls.router())
            logger.info("ANP agent routes registered on ATTP channel")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the unified FastAPI server (WebSocket + ANP + REST)."""
        self._app = FastAPI()
        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self._register_rest_routes()
        self._register_websocket()
        self._register_anp_routes()

        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._running = True
        logger.info("ATTP Channel started at http://{}:{}", self.host, self.port)
        await self._server.serve()

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server:
            self._server.should_exit = True
        for client in self._clients:
            await client.close()
        self._clients.clear()

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        """Send message back to UI via WebSocket (called by ChannelManager)."""
        await self.send_to_ui(msg.content, msg.metadata)

    async def send_to_ui(self, content: str, metadata: dict = None) -> None:
        """Directly send message to UI via WebSocket."""
        session_id = metadata.get("Session_ID") if metadata else None

        payload = {
            "type": "chat",
            "sender": "Local Agent",
            "content": content,
            "Session_ID": session_id,
            "metadata": metadata or {},
        }
        data_str = json.dumps(payload)
        disconnected = []
        for client in self._clients:
            try:
                await client.send_text(data_str)
            except Exception as e:
                logger.error("Failed to send to client: {}", e)
                disconnected.append(client)

        for client in disconnected:
            if client in self._clients:
                self._clients.remove(client)
