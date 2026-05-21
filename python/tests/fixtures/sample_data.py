"""可复用的测试样例数据。"""

from __future__ import annotations

import time
import uuid

from attp.core.message.event import BackMessage, NodeMessage, RecordedHop


def make_session_id() -> str:
    return f"test-session-{uuid.uuid4().hex[:8]}"


def make_nonce() -> str:
    return f"nonce-{uuid.uuid4().hex[:8]}"


def make_recorded_hop(
    session_id: str | None = None,
    sender_did: str = "did:wba:localhost%3A8000:agent:sender",
    target_did: str = "did:wba:localhost%3A8000:agent:receiver",
    content: str = "hello",
    hop_count: list[int] | None = None,
    timestamp: float | None = None,
) -> RecordedHop:
    return RecordedHop(
        session_id=session_id or make_session_id(),
        sender_did=sender_did,
        target_did=target_did,
        content=content,
        timestamp=timestamp or time.time(),
        hop_count=hop_count or [0, 0],
    )


def make_back_message(
    node_did: str,
    nonce: str | None = None,
    session_id: str | None = None,
    sender_did: str | None = None,
    target_did: str | None = None,
    content: str = "hello",
    hop_count: list[int] | None = None,
    protocol_url: str = "http://localhost:9000",
) -> BackMessage:
    hop = make_recorded_hop(
        session_id=session_id or make_session_id(),
        sender_did=sender_did or node_did,
        target_did=target_did or "did:wba:localhost%3A8000:agent:receiver",
        content=content,
        hop_count=hop_count,
    )
    return BackMessage(
        protocol_url=protocol_url,
        node_did=node_did,
        nonce=nonce or make_nonce(),
        sig_identity="",
        recorded_hop=hop,
    )


def make_node_message(
    protocol_url: str = "http://localhost:9000",
    nonce: str | None = None,
    session_id: str | None = None,
    sender_did: str = "did:wba:localhost%3A8000:agent:sender",
    target_did: str = "did:wba:localhost%3A8000:agent:receiver",
    content: str = "hello",
    hop_count: list[int] | None = None,
) -> NodeMessage:
    hop = make_recorded_hop(
        session_id=session_id or make_session_id(),
        sender_did=sender_did,
        target_did=target_did,
        content=content,
        hop_count=hop_count,
    )
    return NodeMessage(
        protocol_url=protocol_url,
        nonce=nonce or make_nonce(),
        recorded_hop=hop,
    )


TEST_AGENT_DID = "did:wba:localhost%3A8000:agent:agent01"
TEST_TOOL_DID = "did:wba:localhost%3A8000:tool:tool01"
TEST_USER_DID = "did:wba:localhost%3A8000:user:user01"
TEST_PNA = "http://localhost:9000"
