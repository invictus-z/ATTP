"""Web UI channel implementation."""
from __future__ import annotations

import asyncio
import json
import uvicorn
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from attp_channel.web_app.api import config_setting, node_status

if TYPE_CHECKING:
    from attp_channel.config.config import WebAppConfig


class WebApp():
    """
    Web UI channel that exposes a WebSocket endpoint for the frontend.
    Focuses on enabling communication with the 'Home (Local Agent)' view.
    """

    def __init__(self, web_config: WebAppConfig, channel_callback=None):
        self.host = web_config.host
        self.port = web_config.port
        self._server = None
        self._serve_task = None
        self._clients: list[WebSocket] = []
        self._channel_callback = channel_callback
        self._app = FastAPI()

        self._app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
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
                            if self._channel_callback:
                                await self._channel_callback(
                                    sender="user",
                                    chat_id=session_id,
                                    content=content,
                                    media=[],
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

    async def start(self, attp_client, attp_config_manager, reload_callback=None) -> None:
        """Start the FastAPI server (non-blocking)."""

        await self.mount_api(attp_client, attp_config_manager, reload_callback)
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        self._running = True
        logger.info(f"WebUI Channel started at http://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False
        if self._server:
            self._server.should_exit = True
        if self._serve_task:
            self._serve_task.cancel()
            try:
                await self._serve_task
            except asyncio.CancelledError:
                pass
        for client in self._clients:
            await client.close()
        self._clients.clear()

    async def mount_api(self, attp_client, attp_config_manager, reload_callback=None):
        # Mount API routes from web_app/api
        from attp_channel.web_app.api import trace
        self._app.include_router(node_status.get_api_router(attp_client))
        self._app.include_router(config_setting.get_api_router(attp_config_manager, reload_callback))
        self._app.include_router(trace.get_api_router())

    async def record_message(self, content: str, metadata: dict | None = None) -> None:
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