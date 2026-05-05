"""Web UI channel implementation."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
import uvicorn
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("WebUI")

from attp.app.web.api import config_setting, node_status

if TYPE_CHECKING:
    from attp.app.config.config import WebAppConfig


class WebApp():
    """
    Web UI channel that exposes a WebSocket endpoint for the frontend.
    Focuses on enabling communication with the 'Home (Local Agent)' view.
    """

    def __init__(self, web_config: WebAppConfig, channel_callback=None, tracer=None):
        self._tracer = tracer
        self.host = web_config.host
        self.port = web_config.port
        self._server = None
        self._serve_task = None
        self._clients: list[WebSocket] = []
        self._channel_callback = channel_callback
        self._app = FastAPI()
        self._session_manager = None
        self._analysis_orchestrator = None
        self._agent_did = ""
        self._active_session_id: str | None = None
        self._on_field_c_recorded = None  # callback(session_id, content)
        self._on_session_end = None       # callback(session_id)

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
            logger.info("Client connected: {}", ws.client)
            try:
                while True:
                    data = await ws.receive_text()
                    try:
                        message_data = json.loads(data)
                        content = message_data.get("content", "")
                        msg_type = message_data.get("type", "chat")
                        # 兼容前端可能使用的小写，但内部统一使用大写 Session_ID
                        session_id = message_data.get("Session_ID") or message_data.get("session_id", "home")

                        # Handle explicit session end
                        if msg_type == "end_session":
                            if self._on_session_end and session_id:
                                await self._on_session_end(session_id)
                            self._active_session_id = None
                            continue

                        # Detect session transition → end old session
                        if msg_type == "chat" and self._active_session_id and session_id != self._active_session_id:
                            if self._on_session_end:
                                await self._on_session_end(self._active_session_id)

                        if msg_type == "chat" and content:
                            self._active_session_id = session_id

                            # Record field U2A: User→Agent
                            await self._record_field_c(session_id, content)

                            # Notify analysis: field c recorded
                            if self._on_field_c_recorded:
                                await self._on_field_c_recorded(session_id, content)

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
                logger.info("Client disconnected: {}", ws.client)
                # End active session on disconnect
                if self._active_session_id and self._on_session_end:
                    await self._on_session_end(self._active_session_id)
                    self._active_session_id = None
                if ws in self._clients:
                    self._clients.remove(ws)
            except Exception as e:
                logger.error("WebSocket error: {}", e)
                if self._active_session_id and self._on_session_end:
                    try:
                        await self._on_session_end(self._active_session_id)
                    except Exception:
                        pass
                    self._active_session_id = None
                if ws in self._clients:
                    self._clients.remove(ws)

    async def start(self, attp_client, attp_config_manager, reload_callback=None,
                    session_manager=None, agent_did: str = "") -> None:
        """Start the FastAPI server (non-blocking)."""

        self._session_manager = session_manager
        self._agent_did = agent_did

        await self.mount_api(attp_client, attp_config_manager, reload_callback)
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
            log_config=UVICORN_SILENT_LOG_CONFIG,
        )
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        self._running = True
        logger.info("started at http://{}:{}", self.host, self.port)

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
        from attp.app.web.api import trace
        self._app.include_router(node_status.get_api_router(attp_client))
        self._app.include_router(config_setting.get_api_router(attp_config_manager, reload_callback))
        self._app.include_router(trace.get_behavior_router(
            self._tracer, self._session_manager, self._analysis_orchestrator,
        ))

        # Serve frontend static files from package-internal static/ directory
        static_dir = Path(__file__).resolve().parent / "static"
        if static_dir.is_dir():
            assets_dir = static_dir / "assets"
            if assets_dir.is_dir():
                self._app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

            @self._app.get("/{full_path:path}")
            async def serve_spa(full_path: str):
                """Serve index.html for all non-API, non-asset routes (SPA fallback)."""
                file_path = static_dir / full_path
                if file_path.is_file():
                    return FileResponse(str(file_path))
                return FileResponse(str(static_dir / "index.html"))

            logger.info("Frontend static files mounted from {}", static_dir)

    async def record_message(self, content: str, metadata: dict | None = None) -> None:
        """Directly send message to UI via WebSocket."""
        session_id = metadata.get("Session_ID") if metadata else None

        # Record field A2U: Agent→User (exclude node message notifications)
        if session_id and not (metadata and metadata.get("is_node_message")):
            await self._record_field_b(session_id, content)

        logger.debug(
            "record_message: session={}, is_node_msg={}, clients={}",
            session_id,
            metadata.get("is_node_message") if metadata else None,
            len(self._clients),
        )

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

    # ------------------------------------------------------------------
    # Behavior recording helpers (fields A2U and U2A)
    # ------------------------------------------------------------------

    async def _record_field_b(self, session_id: str, content: str) -> None:
        """Record field A2U: Agent→User."""
        if not self._session_manager:
            return
        session = self._session_manager.get_or_create(session_id)
        trace = session.get_trace_metadata()
        origin_did = trace.get("Origin_DID", self._agent_did)
        hop_count = session._current_hop_count()

        nm = session.get_or_create_node_message(
            node_did=self._agent_did,
            origin_did=origin_did,
            hop_count=hop_count,
        )
        nm.add_entry(field_type="A2U", content=content)
        self._session_manager.save(session)

        await self._tracer.save_behavior_entry(
            session_id=session_id,
            origin_did=origin_did,
            node_did=self._agent_did,
            hop_count=hop_count,
            field_type="A2U",
            content=content,
            timestamp=time.time(),
        )
        logger.debug("Recorded field A2U: session={}, hop={}", session_id, hop_count)

    async def _record_field_c(self, session_id: str, content: str) -> None:
        """Record field U2A: User→Agent."""
        if not self._session_manager:
            return
        session = self._session_manager.get_or_create(session_id)
        trace = session.get_trace_metadata()
        origin_did = trace.get("Origin_DID", self._agent_did)
        hop_count = session._current_hop_count()

        nm = session.get_or_create_node_message(
            node_did=self._agent_did,
            origin_did=origin_did,
            hop_count=hop_count,
        )
        nm.add_entry(field_type="U2A", content=content)
        self._session_manager.save(session)

        await self._tracer.save_behavior_entry(
            session_id=session_id,
            origin_did=origin_did,
            node_did=self._agent_did,
            hop_count=hop_count,
            field_type="U2A",
            content=content,
            timestamp=time.time(),
        )
        logger.debug("Recorded field U2A: session={}, hop={}", session_id, hop_count)
