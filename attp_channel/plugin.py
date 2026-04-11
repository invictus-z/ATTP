"""ANP ProtocolPlugin implementation — encapsulates all ANP-specific wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from loguru import logger

from nanobot.anp.client import ANPClient
from nanobot.anp.server import ANPServer
from nanobot.anp.tracing import tracer
from nanobot.agent.tools.send_message_tool import SendMessageTool
from nanobot.bus.events import InboundMessage
from nanobot.protocol.base import ProtocolPlugin, ProtocolContext


class ANPPlugin(ProtocolPlugin):
    """Wraps ANPClient + ANPServer + ConfigManager behind the ProtocolPlugin interface."""

    def __init__(self, config_manager):
        self._config_manager = config_manager
        self._anp_cfg = config_manager.anp_config
        self._client: ANPClient | None = None
        self._server: ANPServer | None = None
        self._context: ProtocolContext | None = None
        # Cache the SendMessageTool instance so get_tools() is idempotent
        self._send_tool: SendMessageTool | None = None

    @property
    def name(self) -> str:
        return "anp"

    async def initialize(self, context: ProtocolContext) -> None:
        await super().initialize(context)
        self._context = context

        self._client = ANPClient(
            agent_did=self._anp_cfg.did,
            client_config=self._anp_cfg.anp_client,
            message_bus=context.bus,
        )
        self._server = ANPServer(
            agent_did=self._anp_cfg.did,
            server_config=self._anp_cfg.anp_server,
            message_bus=context.bus,
        )

        self._send_tool = SendMessageTool(
            anp_client=self._client,
            session_manager=context.session_manager,
        )

        await self._client.initialize()
        logger.info("ANPPlugin initialized")

    async def shutdown(self) -> None:
        if self._client:
            self._client.stop_heartbeat()

    # -- Tools --

    def get_tools(self) -> list:
        if self._send_tool is None:
            return []
        return [self._send_tool]

    def update_tool_context(
        self,
        channel: str,
        chat_id: str,
        message_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        if self._send_tool:
            self._send_tool.current_channel = channel
            self._send_tool.current_session_id = session_id or chat_id

    # -- System prompt --

    def get_system_prompt_extension(self) -> str | None:
        return self._build_anp_context()

    def _build_anp_context(self) -> str | None:
        parts: list[str] = []

        # Load guide prompt
        prompt_path = Path(__file__).parent.parent / "agent" / "prompts" / "anp_guide.md"
        if prompt_path.exists():
            parts.append(prompt_path.read_text(encoding="utf-8"))

        # Inject known agent info from discovery
        if self._client:
            online_dids = set(self._client._remote_agents.keys())
            if hasattr(self._client, "registered_agents"):
                for did, remote in self._client.registered_agents.items():
                    if did not in online_dids:
                        continue
                    name = getattr(remote, "name", "") or did
                    desc = getattr(remote, "description", "") or ""
                    capabilities = getattr(remote, "capabilities", []) or []
                    block = f"## Known Agent: {name}\n"
                    block += f"- DID: `{did}`\n"
                    block += f"- Description: {desc}\n"
                    if capabilities:
                        block += f"- Capabilities: {', '.join(capabilities)}\n"
                    block += "- Status: Online\n"
                    parts.append(block)

        return "\n\n".join(parts) if parts else None

    # -- Message preprocessing --

    async def on_inbound_message(
        self, msg: InboundMessage, session
    ) -> InboundMessage | None:
        """Handle ANP message routing: re-key session and store trace metadata."""
        if msg.channel != "anp" or not msg.metadata:
            return msg

        user_session_id = msg.metadata.get("Session_ID")
        if user_session_id and user_session_id != "UNKNOWN_SESSION":
            msg.session_key_override = f"web_ui:{user_session_id}"
            logger.debug(
                f"ANP message routing to user session: web_ui:{user_session_id}"
            )

        session.set_trace_metadata(msg.metadata)
        logger.debug(
            f"Saved trace metadata: {msg.metadata.get('Session_ID')}"
        )

        return msg

    # -- API routes --

    def get_api_router(self) -> APIRouter:
        router = APIRouter(prefix="/api")

        @router.get("/nodes")
        async def get_nodes():
            if not self._client:
                return {"agents": []}
            online_dids = set(self._client._remote_agents.keys())
            agents = []
            for did, info in self._client._registered_agents.items():
                agents.append(
                    {
                        "did": info.get("did", did),
                        "name": info.get("name", ""),
                        "description": info.get("description", ""),
                        "ad_url": info.get("ad_url", ""),
                        "capabilities": info.get("capabilities", []),
                        "online": did in online_dids,
                    }
                )
            return {"agents": agents}

        @router.get("/traces/{session_id}")
        async def get_session_trace(session_id: str):
            from datetime import datetime
            import logging as _logging

            _logger = _logging.getLogger(__name__)
            try:
                rows = tracer.recover_trace(session_id)
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
                _logger.error(f"Error recovering trace for {session_id}: {e}")
                return {
                    "Session_ID": session_id,
                    "Intent_Tag": "Error",
                    "Path": [],
                }

        @router.get("/config")
        async def get_config():
            if not self._config_manager:
                return {"error": "ANP is not enabled", "config": None}
            return {
                "config": self._config_manager.anp_config.model_dump(by_alias=True)
            }

        @router.put("/config")
        async def update_config(request: Request):
            if not self._config_manager:
                return {"error": "ANP is not enabled"}
            try:
                partial = await request.json()
                updated = self._config_manager.update(partial)
                return {
                    "success": True,
                    "config": updated.model_dump(by_alias=True),
                }
            except Exception as e:
                logger.error(f"Error updating ANP config: {e}")
                return {"success": False, "error": str(e)}

        return router

    # -- Background tasks --

    def get_background_tasks(self) -> list:
        tasks = []
        if self._server:
            tasks.append(self._server.start())
        return tasks

    # -- Status --

    def get_status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": "active" if self._client else "uninitialized",
            "remote_agents": (
                len(self._client._remote_agents) if self._client else 0
            ),
        }
