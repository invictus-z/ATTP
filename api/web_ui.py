"""Web UI channel implementation."""
from __future__ import annotations

import asyncio
import json
import uvicorn
from typing import Any, TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


class WebUIChannel(BaseChannel):
    """
    Web UI channel that exposes a WebSocket endpoint for the frontend.
    Focuses on enabling communication with the 'Home (Local Agent)' view.
    """

    name: str = "web_ui"

    def __init__(self, config: Any, bus: MessageBus, session_manager: "SessionManager" = None, plugins: list | None = None):
        super().__init__(config, bus)
        # Fix port resolution to be sure
        self.host = getattr(config, "host", "127.0.0.1")
        self.port = getattr(config, "port", 8001)
        self._server = None
        self._clients: list[WebSocket] = []
        self._app = FastAPI()
        self.session_manager = session_manager
        self.plugins = plugins or []

        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        
        @self._app.get("/api/status")
        async def get_status():
            """Return the local agent's running status and WebSocket client count."""
            return {
                "status": "active" if self._running else "offline",
                "ws_clients": len(self._clients),
            }


        # Mount plugin API routes
        for plugin in self.plugins:
            router = plugin.get_api_router()
            if router is not None:
                self._app.include_router(router)

        @self._app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            await ws.accept()
            self._clients.append(ws)
            logger.info(f"WebUI Client connected: {ws.client}")
            try:
                while True:
                    data = await ws.receive_text()
                    try:
                        message_data = json.loads(data)
                        content = message_data.get("content", "")
                        msg_type = message_data.get("type", "chat")
                        # 兼容前端可能使用的小写，但内部统一使用大写 Session_ID
                        session_id = message_data.get("Session_ID") or message_data.get("session_id", "home")

                        if msg_type == "chat" and content:
                            # Build metadata - 统一使用大写 Session_ID
                            # trace_metadata 由 send_message_tool 在发送给 agent 时自己获取
                            metadata = {"Session_ID": session_id}

                            await self._handle_message(
                                sender_id="user",
                                chat_id=session_id,
                                content=content,
                                metadata=metadata
                            )
                    except json.JSONDecodeError:
                        logger.warning("Received invalid JSON over WebSocket")
            except WebSocketDisconnect:
                logger.info(f"WebUI Client disconnected: {ws.client}")
                if ws in self._clients:
                    self._clients.remove(ws)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                if ws in self._clients:
                    self._clients.remove(ws)

    async def start(self) -> None:
        """Start the FastAPI server."""
        config = uvicorn.Config(
            self._app, 
            host=self.host, 
            port=self.port, 
            log_level="info"
        )
        self._server = uvicorn.Server(config)
        self._running = True
        logger.info(f"WebUI Channel started at http://{self.host}:{self.port}")
        await self._server.serve()

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server:
            self._server.should_exit = True
        for client in self._clients:
            await client.close()
        self._clients.clear()

    async def send(self, msg: OutboundMessage) -> None:
        """Send message back to UI via WebSocket."""
        session_id = None
        if msg.metadata:
            session_id = msg.metadata.get("Session_ID")

        payload = {
            "type": "chat",
            "sender": "Local Agent",
            "content": msg.content,
            "Session_ID": session_id,
            "metadata": msg.metadata if hasattr(msg, 'metadata') and msg.metadata else {}
        }
        data_str = json.dumps(payload)
        disconnected = []
        for client in self._clients:
            try:
                await client.send_text(data_str)
            except Exception as e:
                logger.error(f"Failed to send to client: {e}")
                disconnected.append(client)
        
        for client in disconnected:
            if client in self._clients:
                self._clients.remove(client)
