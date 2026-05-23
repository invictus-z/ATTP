"""Web UI channel implementation — WebSocket + 通用 API（config/node_status）+ SPA。

协议相关 API（trace/analysis）已迁移至 ProtocolNode ApiPort。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
import uvicorn
from typing import TYPE_CHECKING

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG
from attp.core.message.event import NodeMessage, RecordedHop
from attp.core.message.back_sender import send_back_message

logger = get_logger("WebUI")

from attp.app.web.api import config_setting, node_status

if TYPE_CHECKING:
    from attp.app.config.config import WebAppConfig


class WebApp():
    """
    Web UI channel that exposes a WebSocket endpoint for the frontend,
    plus general-purpose API routes (config, node_status).
    Protocol-related API routes (trace, analysis) are served by ProtocolNode ApiPort.
    """

    def __init__(self, web_config: WebAppConfig, channel_callback=None):
        self.host = web_config.host
        self.port = web_config.port
        self._server = None
        self._serve_task = None
        self._clients: list[WebSocket] = []
        self._channel_callback = channel_callback
        self._app = FastAPI()
        self._session_manager = None
        self._agent_did = ""
        self._active_session_id: str | None = None
        self._tracer = None
        self._private_key_path = ""

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

                        # === 统一 NodeMessage 格式 ===
                        # 前端直接发送 NodeMessage.to_dict() 的 JSON
                        try:
                            node_msg = NodeMessage.from_dict(message_data)
                        except (KeyError, TypeError):
                            logger.warning("Received non-NodeMessage JSON over WebSocket")
                            continue

                        session_id = node_msg.recorded_hop.session_id
                        content = node_msg.recorded_hop.content

                        self._active_session_id = session_id

                        # === U2A Phase 1 回传：回传协议节点 ===
                        if self._tracer and self._private_key_path and self._agent_did:
                            try:
                                if self._session_manager:
                                    session = self._session_manager.get_or_create(session_id)
                                    session.set_trace_metadata({
                                        "recorded_hop": node_msg.recorded_hop.to_dict(),
                                        "protocol_url": node_msg.protocol_url,
                                    })
                                    self._session_manager.save(session)
                                private_key = self._tracer.load_private_key(self._private_key_path)
                                await send_back_message(
                                    protocol_url=node_msg.protocol_url,
                                    node_did=self._agent_did,
                                    nonce=node_msg.nonce,
                                    recorded_hop=node_msg.recorded_hop,
                                    private_key=private_key,
                                )
                            except Exception as e:
                                logger.warning("U2A Phase 1 callback failed: {}", e)

                        # 路由到 nanobot 处理
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
                self._active_session_id = None
                if ws in self._clients:
                    self._clients.remove(ws)
            except Exception as e:
                logger.error("WebSocket error: {}", e)
                self._active_session_id = None
                if ws in self._clients:
                    self._clients.remove(ws)

    async def start(self, attp_client, attp_config_manager, reload_callback=None,
                    session_manager=None, agent_did: str = "",
                    tracer=None, private_key_path: str = "") -> None:
        """Start the FastAPI server (non-blocking)."""

        self._session_manager = session_manager
        self._agent_did = agent_did
        self._tracer = tracer
        self._private_key_path = private_key_path

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
        # Mount general-purpose API routes (config, node_status)
        self._app.include_router(node_status.get_api_router(attp_client))
        self._app.include_router(config_setting.get_api_router(attp_config_manager, reload_callback))
        # Note: trace/analysis API routes are served by ProtocolNode ApiPort

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

    async def send_message_to_user(self, content: str, session_id: str) -> None:
        """构建 A2U NodeMessage 并发送给 User。

        完整流程：
          1. 从 session trace 获取协议节点 URL 和上一跳信息
          2. 构建 A2U RecordedHop（Agent → User）
          3. 回传协议节点（BackMessage）
          4. 更新 session trace
          5. 通过 WS 发送 NodeMessage 给 User
        """
        logger.warning("[DEBUG-DUP] send_message_to_user called: session={}, content_len={}, ws_clients={}",
                       session_id, len(content), len(self._clients))
        try:
            session = self._session_manager.get(session_id) if self._session_manager else None
            trace = session.get_trace_metadata() if session else None

            if trace and self._tracer and self._private_key_path and self._agent_did:
                protocol_url = trace.get("protocol_url", "")
                prev_hop_dict = trace.get("recorded_hop", {})
                user_did = prev_hop_dict.get("sender_did", "")

                if protocol_url and user_did:
                    hop_metadata = self._tracer.append_hop(
                        metadata=dict(trace),
                        content=content,
                        node_did=self._agent_did,
                        target_did=user_did,
                        private_key_path=self._private_key_path,
                        behavior_type="A2U",
                    )
                    hop = hop_metadata.get("recorded_hop")
                    if hop:
                        recorded = RecordedHop.from_dict(hop)
                        nonce = uuid.uuid4().hex
                        node_msg = NodeMessage(
                            protocol_url=protocol_url,
                            nonce=nonce,
                            recorded_hop=recorded,
                        )
                        # 时序规则：先回传协议节点
                        private_key = self._tracer.load_private_key(self._private_key_path)
                        await send_back_message(
                            protocol_url=protocol_url,
                            node_did=self._agent_did,
                            nonce=nonce,
                            recorded_hop=recorded,
                            private_key=private_key,
                        )
                        # 更新 session trace
                        if session:
                            session.set_trace_metadata({
                                "recorded_hop": hop,
                                "protocol_url": protocol_url,
                            })
                            self._session_manager.save(session)

                        # 序列化 NodeMessage 并 WS 发送
                        data_str = json.dumps(node_msg.to_dict())
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
                        return

            # 无 trace 信息时降级
            logger.warning("send_message_to_user: no trace metadata for session={}", session_id)
        except Exception as e:
            logger.error("send_message_to_user: A2U NodeMessage 构建失败: {}", e)

        # 降级：无法构建 NodeMessage，消息被丢弃
        logger.warning("send_message_to_user: fallback — message dropped for session={}", session_id)

    async def record_message(self, content: str, metadata: dict | None = None) -> None:
        """Directly send message to UI via WebSocket.

        For messages from ATTPChannel.send() (no NodeMessage/is_node_message in
        metadata), performs A2U back-propagation: builds RecordedHop, sends
        BackMessage to protocol node, and includes NodeMessage in the payload.
        """
        return  # 已被 send_message_to_user 替代
        metadata = metadata or {}
        session_id = metadata.get("Session_ID")

        # === A2U 回传判断 ===
        # 若 metadata 中已有  is_A2A_message，
        # 说明调用方为client/server，跳过
        if not (metadata.get("is_A2A_message")):
            if session_id and self._tracer and self._private_key_path and self._agent_did:
                try:
                    session = self._session_manager.get(session_id) if self._session_manager else None
                    trace = session.get_trace_metadata() if session else None

                    if trace:
                        protocol_url = trace.get("protocol_url", "")
                        prev_hop_dict = trace.get("recorded_hop", {})
                        user_did = prev_hop_dict.get("sender_did", "")

                        if protocol_url and user_did:
                            hop_metadata = self._tracer.append_hop(
                                metadata=dict(trace),
                                content=content,
                                node_did=self._agent_did,
                                target_did=user_did,
                                private_key_path=self._private_key_path,
                                behavior_type="A2U",
                            )
                            hop = hop_metadata.get("recorded_hop")
                            if hop:
                                recorded = RecordedHop.from_dict(hop)
                                nonce = uuid.uuid4().hex
                                node_msg = NodeMessage(
                                    protocol_url=protocol_url,
                                    nonce=nonce,
                                    recorded_hop=recorded,
                                )
                                # 时序规则：先回传协议节点
                                private_key = self._tracer.load_private_key(self._private_key_path)
                                await send_back_message(
                                    protocol_url=protocol_url,
                                    node_did=self._agent_did,
                                    nonce=nonce,
                                    recorded_hop=recorded,
                                    private_key=private_key,
                                )
                                # 更新 session trace
                                session.set_trace_metadata({
                                    "recorded_hop": hop,
                                    "protocol_url": protocol_url,
                                })
                                self._session_manager.save(session)
                                # 将 NodeMessage 放入 metadata（前端会用它做 Phase 2 回传）
                                metadata["NodeMessage"] = node_msg.to_dict()
                except Exception as e:
                    logger.warning("A2U back-propagation in record_message failed: {}", e)

        logger.debug(
            "record_message: session={}, has_node_msg={}, clients={}",
            session_id,
            bool(metadata.get("NodeMessage")),
            len(self._clients),
        )

        payload = {
            "type": "chat",
            "sender": "Local Agent",
            "content": content,
            "Session_ID": session_id,
            "metadata": metadata,
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
