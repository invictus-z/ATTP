"""openclaw ATTP adapter — reuse every ATTP component, change zero existing files.

The wiring is a direct translation of attp/channels/nanobot.py ATTPChannel.start().
Only two seams differ from nanobot:
  * inbound  — WebApp.channel_callback (U2A) and ATTPServer.attp_channel_callback (A2A)
    forward to the openclaw gateway's HTTP webhook (POST /attp/inbound).
  * outbound — the openclaw agent's reply is delivered via the /openclaw/reply route
    (mounted on the WebApp) -> WebApp.send_message_to_user.

Everything else (A2A transport, provenance, protocol-node back-propagation, tools)
is handled by the framework-agnostic ATTP components and is identical to nanobot.
"""
from __future__ import annotations

import asyncio

from attp.app.client import ATTPClient
from attp.app.config import ConfigManager
from attp.app.heartbeat import AgentHealthChecker, HeartbeatManager, ToolNodeHealthChecker
from attp.app.logging import get_logger
from attp.app.server import ATTPServer
from attp.app.tools import MCPToolBridge
from attp.app.web import WebApp
from attp.channels.openclaw.bridge import build_inbound_payload, mount_reply_route, post_inbound
from attp.core.agent_tracer import AgentTracer
from attp.core.sessions.app import AppSessionManager

logger = get_logger("OpenclawAdapter")


class OpenclawATTPAdapter:
    """Construct + serve the full ATTP component graph, bridged to openclaw over HTTP."""

    def __init__(self, *, config_path: str, webhook_url: str, token: str) -> None:
        self._config_path = config_path
        self._webhook_url = webhook_url
        self._token = token
        self._running = False
        self._protocol_node = None

    # -- inbound forwarding -------------------------------------------------

    def _make_forwarder(self, direction: str):
        """Return an (sender, chat_id, content, media) -> 'ok' callback.

        The callback builds the inbound payload and POSTs it to the openclaw
        webhook. `direction` ("U2A" | "A2A") is exposed on the callable for
        introspection and is carried in the payload so the openclaw side can tell
        user-originated messages from agent-originated ones.
        """
        webhook_url, token = self._webhook_url, self._token

        async def _forward(sender, chat_id, content, media):
            await post_inbound(
                webhook_url, token,
                build_inbound_payload(
                    session_id=chat_id, sender_did=sender,
                    content=content, direction=direction,
                ),
            )
            return "ok"

        _forward.direction = direction
        return _forward

    # -- construction (sync, testable) --------------------------------------

    def _build(self) -> None:
        """Construct all ATTP components and wire the two host seams.

        Mirrors ATTPChannel.start() lines that build ConfigManager -> ...
        -> MCPToolBridge -> (optional) ProtocolNode. Does NOT start anything;
        run() starts the components after discovery.
        """
        self._config_manager = ConfigManager(self._config_path)
        cfg = self._config_manager.attp_config

        self._u2a_cb = self._make_forwarder("U2A")
        self._a2a_cb = self._make_forwarder("A2A")

        self._agent_tracer = AgentTracer()
        self._web_app = WebApp(
            web_config=cfg.web_app,
            channel_callback=self._u2a_cb,
        )
        self._app_session_manager = AppSessionManager()
        self._attp_client = ATTPClient(
            agent_did=cfg.did,
            client_config=cfg.attp_client,
            session_manager=self._app_session_manager,
            web_callback=self._web_app.record_message,
            tracer=self._agent_tracer,
        )
        self._attp_server = ATTPServer(
            agent_did=cfg.did,
            server_config=cfg.attp_server,
            session_manager=self._app_session_manager,
            web_callback=self._web_app.record_message,
            attp_channel_callback=self._a2a_cb,
            tracer=self._agent_tracer,
        )
        self._heartbeat_manager = HeartbeatManager(cfg.heartbeat)
        self._heartbeat_manager.add_checker(AgentHealthChecker(
            attp_client=self._attp_client,
            timeout=cfg.heartbeat.timeout,
            max_fail=cfg.heartbeat.max_fail,
        ))
        self._tool_bridge = MCPToolBridge(
            tool_config=cfg.tool,
            attp_client=self._attp_client,
            tracer=self._agent_tracer,
            session_manager=self._app_session_manager,
            agent_did=cfg.did,
            send_callback=self._attp_client.send_message,
        )
        self._heartbeat_manager.add_checker(ToolNodeHealthChecker(
            tool_bridge=self._tool_bridge,
            timeout=cfg.heartbeat.timeout,
            max_fail=cfg.heartbeat.max_fail,
        ))

        # outbound: openclaw agent reply -> WebApp.send_message_to_user
        mount_reply_route(self._web_app)

        # optional ProtocolNode (provenance / trace / analysis)
        self._protocol_node = None
        if cfg.protocol_node.enabled:
            from attp.protocol_node import ProtocolNode

            self._protocol_node = ProtocolNode(config_path=cfg.protocol_node.config_path)

    # -- serve --------------------------------------------------------------

    async def run(self) -> None:
        self._running = True
        self._build()
        cfg = self._config_manager.attp_config

        if cfg.tool.tool_node_ads:
            await self._tool_bridge.discover_all_tool_nodes(cfg.tool.tool_node_ads)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._attp_client.start())
            tg.create_task(self._attp_server.start())
            tg.create_task(self._heartbeat_manager.start())
            tg.create_task(self._tool_bridge.start())
            tg.create_task(self._web_app.start(
                self._attp_client, self._config_manager,
                reload_callback=lambda *a, **k: None,
                session_manager=self._app_session_manager,
                agent_did=cfg.did,
                tracer=self._agent_tracer,
                private_key_path=str(self._attp_client.auth.private_key_path),
            ))
            if self._protocol_node:
                tg.create_task(self._protocol_node.start())

        logger.info("ATTP openclaw adapter ready; webhook={}", self._webhook_url)
        while self._running:
            await asyncio.sleep(1)

        # graceful shutdown
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_manager.stop())
            tg.create_task(self._tool_bridge.stop())
            tg.create_task(self._attp_client.stop())
            tg.create_task(self._attp_server.stop())
            tg.create_task(self._web_app.stop())
            if self._protocol_node:
                tg.create_task(self._protocol_node.stop())

    def stop(self) -> None:
        self._running = False
