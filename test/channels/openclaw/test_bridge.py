"""Tests for attp.channels.openclaw.bridge — HTTP bridge payload + reply route."""
from attp.channels.openclaw.bridge import build_inbound_payload


def test_payload_u2a():
    p = build_inbound_payload(
        session_id="S1", sender_did="user", content="hi", direction="U2A"
    )
    assert p == {"session_id": "S1", "sender_did": "user", "content": "hi", "direction": "U2A"}


def test_payload_a2a_carries_sender_did():
    # A2A 必须带远端 Agent DID，供 openclaw agent 用 send_message_tool(target=...) 回复
    p = build_inbound_payload(
        session_id="S2", sender_did="did:wba:host:nanobot", content="ping", direction="A2A"
    )
    assert p["sender_did"] == "did:wba:host:nanobot"
    assert p["direction"] == "A2A"


from fastapi import FastAPI
from fastapi.testclient import TestClient

from attp.channels.openclaw.bridge import mount_reply_route


class FakeWebApp:
    """Stand-in for attp.app.web.WebApp: just needs ._app + send_message_to_user."""

    def __init__(self):
        self._app = FastAPI()
        self.sent: list[tuple[str, str]] = []

    async def send_message_to_user(self, content: str, session_id: str) -> None:
        self.sent.append((session_id, content))


def test_reply_route_calls_send_message_to_user():
    web_app = FakeWebApp()
    mount_reply_route(web_app)
    client = TestClient(web_app._app)
    r = client.post("/openclaw/reply", json={"session_id": "S9", "content": "hello"})
    assert r.status_code == 200
    assert web_app.sent == [("S9", "hello")]


def test_reply_route_rejects_missing_fields():
    web_app = FakeWebApp()
    mount_reply_route(web_app)
    client = TestClient(web_app._app)
    r = client.post("/openclaw/reply", json={"session_id": "S9"})  # missing content
    assert r.status_code == 422
