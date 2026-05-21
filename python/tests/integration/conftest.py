"""集成测试共享 fixtures — FastAPI 测试客户端 + 真实 SQLite。"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.core.pn_tracer import ProtocolTracer
from attp.core.sessions.protocol_node.manager import ProtocolSessionManager
from attp.protocol_node.engine.behavior_controller import BehaviorController
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector
from attp.protocol_node.ports.protocol_port import ProtocolPort

from tests.fixtures.crypto_helpers import build_did_resolution_result
from tests.fixtures.sample_data import (
    TEST_AGENT_DID,
    TEST_TOOL_DID,
    TEST_USER_DID,
    make_back_message,
    make_session_id,
    make_nonce,
)


@pytest_asyncio.fixture
async def tracer(tmp_path):
    db_path = str(tmp_path / "test.db")
    t = await ProtocolTracer.create(db_path)
    return t


@pytest_asyncio.fixture
def session_manager():
    return ProtocolSessionManager()


@pytest_asyncio.fixture
def behavior_controller():
    return BehaviorController()


@pytest_asyncio.fixture
def mock_did_resolver(agent_keys, tool_keys, user_keys):
    resolver = AsyncMock()
    results = {}
    results[TEST_AGENT_DID] = build_did_resolution_result(TEST_AGENT_DID, agent_keys[1], "agent")
    results[TEST_TOOL_DID] = build_did_resolution_result(TEST_TOOL_DID, tool_keys[1], "tool")
    results[TEST_USER_DID] = build_did_resolution_result(TEST_USER_DID, user_keys[1], "user")

    async def _resolve_full(did, key_fragment="key-1"):
        return results.get(did, DIDResolutionResult(public_key=None, node_type=None, did_document=None))

    resolver.resolve_full = _resolve_full
    return resolver


@pytest_asyncio.fixture
def malicious_detector(mock_did_resolver):
    return MaliciousNodeDetector(mock_did_resolver)


@pytest_asyncio.fixture
async def app(tracer, session_manager, mock_did_resolver, behavior_controller, malicious_detector):
    port = ProtocolPort(
        tracer=tracer,
        session_manager=session_manager,
        host="0.0.0.0",
        port=9000,
        did_resolver=mock_did_resolver,
        behavior_controller=behavior_controller,
        malicious_detector=malicious_detector,
    )
    return port._app


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _make_signed_bp(
    node_did: str,
    nonce: str,
    session_id: str,
    sender_did: str,
    target_did: str,
    private_key,
    content: str = "hello",
    hop_count: list[int] | None = None,
    protocol_url: str = "http://localhost:9000",
    content_sig: str | None = None,
    content_key=None,
    timestamp: float | None = None,
) -> dict:
    """Build a signed BackMessage dict.

    private_key: used for identity signature (the node back-propagating).
    content_key: used for content signature (the original sender). If None, uses private_key.
    content_sig: pre-computed sig_content to use (both BPs must share the same sig).
    timestamp: fixed timestamp for the recorded_hop (must match content_sig computation).
    """
    msg = make_back_message(
        node_did=node_did,
        nonce=nonce,
        session_id=session_id,
        sender_did=sender_did,
        target_did=target_did,
        content=content,
        hop_count=hop_count or [0, 0],
        protocol_url=protocol_url,
    )
    if timestamp is not None:
        msg.recorded_hop.timestamp = timestamp
    msg.sign_identity(private_key)
    if content_sig is not None:
        msg.recorded_hop.sig_content = content_sig
    else:
        msg.sign_content(content_key if content_key is not None else private_key)
    return msg.to_dict()
