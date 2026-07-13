"""openclaw <-> ATTP HTTP bridge: inbound forward + outbound reply route.

Inbound  (ATTP -> openclaw): build_inbound_payload + post_inbound  -> POST <gateway>/attp/inbound
Outbound (openclaw -> ATTP): mount_reply_route -> POST /openclaw/reply -> WebApp.send_message_to_user
"""
from __future__ import annotations

from typing import Any

import aiohttp

from attp.app.logging import get_logger

logger = get_logger("OpenclawBridge")


def build_inbound_payload(
    *, session_id: str, sender_did: str, content: str, direction: str
) -> dict[str, Any]:
    """Build the JSON body posted to the openclaw inbound webhook.

    direction is "U2A" (user -> brain via WebApp) or "A2A" (remote agent -> brain
    via ATTPServer). sender_did is carried so the openclaw agent can answer an
    A2A message with send_message_tool(target=sender_did, chat_id=session_id).
    """
    return {
        "session_id": session_id,
        "sender_did": sender_did,
        "content": content,
        "direction": direction,
    }


async def post_inbound(
    webhook_url: str, token: str, payload: dict[str, Any], timeout: float = 10.0
) -> None:
    """POST an inbound payload to the openclaw webhook.

    Failures are logged but never raised: the ATTP pipeline must not block on the
    host gateway being momentarily unreachable.
    """
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with aiohttp.ClientSession() as http:
            async with http.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status >= 300:
                    logger.warning("openclaw webhook returned HTTP {}", resp.status)
    except Exception as e:  # noqa: BLE001
        logger.warning("post_inbound failed: {}", e)


from pydantic import BaseModel


class _ReplyBody(BaseModel):
    """Body for POST /openclaw/reply: the openclaw agent's reply to deliver."""

    session_id: str
    content: str


def mount_reply_route(web_app) -> None:
    """Mount POST /openclaw/reply on a WebApp's FastAPI app.

    Routes the openclaw agent's normal (A2U) reply to WebApp.send_message_to_user,
    which builds the A2U NodeMessage, back-propagates to the protocol node, and
    pushes to the browser WebSocket. Must be called before web_app.start() so the
    route is served on the same port as the WebUI.
    """
    send = web_app.send_message_to_user

    @web_app._app.post("/openclaw/reply")
    async def _openclaw_reply(body: _ReplyBody):
        await send(body.content, body.session_id)
        return {"ok": True}

