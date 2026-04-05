"""MCP Server that exposes *send_message_tool* via stdio transport.

This replaces the former nanobot ``Tool`` subclass with a standard MCP tool.
The only tool exposed is ``send_message_tool`` which accepts three parameters:

- ``target``  – "user:web_ui" or an agent DID ("did:wba:...")
- ``content`` – message body
- ``chat_id`` – session identifier used for routing and trace tracking
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from sessions import SessionManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state – injected by ``run_server()`` or loaded from env vars
# ---------------------------------------------------------------------------
_anp_client: Any = None          # ANPClient instance
_session_manager: SessionManager | None = None


def _init_from_env() -> None:
    """Initialise ANPClient and SessionManager from environment variables.

    Environment variables consumed:
        ATTP_ANP_CONFIG  – path to ``anp_config.json``
        ATTP_AGENT_DID   – DID string for this agent
        ATTP_SESSION_DIR – (optional) directory for session storage

    This is used when the MCP server runs as a standalone stdio subprocess.
    """
    global _anp_client, _session_manager

    session_dir = sys.getenv("ATTP_SESSION_DIR")
    _session_manager = SessionManager(storage_dir=session_dir)

    config_path = sys.getenv("ATTP_ANP_CONFIG")
    agent_did = sys.getenv("ATTP_AGENT_DID")

    if config_path and agent_did:
        try:
            # Lazy import to avoid hard dependency when not needed
            from attp_channel.client import ANPClient
            from attp_channel.config_manager import ANPClientConfig

            config_data = json.loads(Path(config_path).read_text(encoding="utf-8"))
            config = ANPClientConfig(**config_data)
            _anp_client = ANPClient(agent_did=agent_did, client_config=config)
            logger.info("ANPClient initialised from env for DID %s", agent_did)
        except Exception:
            logger.exception("Failed to initialise ANPClient from environment")


# ---------------------------------------------------------------------------
# MCP Server definition
# ---------------------------------------------------------------------------

app = Server("attp-send-message")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Declare the single *send_message_tool*."""
    return [
        Tool(
            name="send_message_tool",
            description=(
                "必须且只能使用此工具来发送消息给主人或其他 Agent。"
                "绝对不允许尝试自己构造或使用 JSON-RPC 等不存在或未经定义的接口。"
                "如果你找不到工具，请回复 '我无法找到发送消息工具'。\n\n"
                "参数说明：\n"
                "- target: 目标地址。发给主人使用 \"user:web_ui\"；"
                "发给其他 agent 使用对应节点的完整 DID，"
                "例如 \"did:wba:home.local:furniture-manager\"\n"
                "- content: 消息内容\n"
                "- chat_id: 当前会话ID，用于路由和追踪"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": (
                            "目标地址：'user:web_ui' 发给主人，"
                            "'did:wba:...' 发给其他 Agent"
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "消息内容",
                    },
                    "chat_id": {
                        "type": "string",
                        "description": "会话 ID，用于路由和追踪",
                    },
                },
                "required": ["target", "content", "chat_id"],
            },
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute *send_message_tool*."""
    if name != "send_message_tool":
        return [TextContent(type="text", text=f"Error: Unknown tool '{name}'")]

    target = arguments.get("target", "")
    content = arguments.get("content", "")
    chat_id = arguments.get("chat_id", "")

    if not target or not content or not chat_id:
        return [
            TextContent(
                type="text",
                text="Error: target, content and chat_id are all required.",
            )
        ]

    if _anp_client is None:
        return [TextContent(type="text", text="Error: ANPClient not initialised.")]

    if _session_manager is None:
        return [TextContent(type="text", text="Error: SessionManager not initialised.")]

    session = _session_manager.get_or_create(chat_id)

    # ----- send to user -----
    if target.startswith("user:"):
        channel = target.split(":")[1] if ":" in target else "web_ui"
        try:
            result = await _anp_client.send_to_user(
                channel=channel,
                current_session_id=chat_id,
                content=content,
            )
        except Exception as exc:
            logger.exception("send_to_user failed")
            result = f"Error: {exc}"
        return [TextContent(type="text", text=result)]

    # ----- send to agent -----
    if target.startswith("did:"):
        sender_did = _anp_client.agent_did

        # Retrieve accumulated trace metadata from the session
        trace_metadata = session.get_trace_metadata()
        metadata: dict[str, Any] = {"Session_ID": chat_id}
        if trace_metadata:
            metadata.update(trace_metadata)

        try:
            result = await _anp_client.send_to_agent(
                target_did=target,
                sender_did=sender_did,
                content=content,
                message_type="agent_request",
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("send_to_agent failed")
            return [TextContent(type="text", text=f"Error: {exc}")]

        # Persist updated trace path back to session
        if "Path" in metadata:
            session.set_trace_metadata({"Path": metadata["Path"]})
            _session_manager.save(session)

        return [TextContent(type="text", text=result if isinstance(result, str) else str(result))]

    return [
        TextContent(
            type="text",
            text="Error: Invalid target format. Use 'user:web_ui' or 'did:wba:...'",
        )
    ]


# ---------------------------------------------------------------------------
# Public entry-points
# ---------------------------------------------------------------------------

async def run_server(
    anp_client: Any = None,
    session_manager: SessionManager | None = None,
) -> None:
    """Start the MCP server over stdio.

    Can be called in two ways:

    1. **Dependency injection** – pass *anp_client* and *session_manager*
       directly (typical when embedded in the main process).
    2. **Standalone subprocess** – omit arguments; the server will attempt
       to initialise from environment variables (``ATTP_*``).
    """
    global _anp_client, _session_manager

    if anp_client is not None:
        _anp_client = anp_client
    if session_manager is not None:
        _session_manager = session_manager

    # Fallback: try env-var initialisation if no client was injected
    if _anp_client is None:
        _init_from_env()

    if _session_manager is None:
        _session_manager = SessionManager()

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


def main() -> None:
    """CLI entry-point for ``python -m tools.send_message_tool``."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
