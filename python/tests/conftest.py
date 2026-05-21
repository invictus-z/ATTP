"""共享测试 fixtures。"""

from __future__ import annotations

import os
import tempfile
from typing import Any
from unittest.mock import AsyncMock

import pytest

from attp.core.authentication.keys import KeyStore
from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.core.sessions.protocol_node.manager import ProtocolSessionManager
from attp.core.sessions.protocol_node.session import ProtocolSession
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector

from tests.fixtures.crypto_helpers import (
    generate_rsa_keypair,
    generate_secp256k1_keypair,
    generate_p256_keypair,
    build_did_resolution_result,
)
from tests.fixtures.sample_data import (
    TEST_AGENT_DID,
    TEST_TOOL_DID,
    TEST_USER_DID,
)


@pytest.fixture
def rsa_keys():
    private, public = generate_rsa_keypair()
    return private, public


@pytest.fixture
def secp256k1_keys():
    private, public = generate_secp256k1_keypair()
    return private, public


@pytest.fixture
def p256_keys():
    private, public = generate_p256_keypair()
    return private, public


@pytest.fixture
def agent_keys():
    private, public = generate_secp256k1_keypair()
    return private, public


@pytest.fixture
def tool_keys():
    private, public = generate_p256_keypair()
    return private, public


@pytest.fixture
def user_keys():
    private, public = generate_secp256k1_keypair()
    return private, public


@pytest.fixture
def key_store():
    return KeyStore()


@pytest.fixture
def session_manager():
    return ProtocolSessionManager()


@pytest.fixture
def tmp_db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def mock_did_resolver(agent_keys, tool_keys, user_keys):
    resolver = AsyncMock()
    results = {}

    agent_pub = agent_keys[1]
    tool_pub = tool_keys[1]
    user_pub = user_keys[1]

    results[TEST_AGENT_DID] = build_did_resolution_result(
        TEST_AGENT_DID, agent_pub, "agent"
    )
    results[TEST_TOOL_DID] = build_did_resolution_result(
        TEST_TOOL_DID, tool_pub, "tool"
    )
    results[TEST_USER_DID] = build_did_resolution_result(
        TEST_USER_DID, user_pub, "user"
    )

    async def _resolve_full(did, key_fragment="key-1"):
        if did in results:
            return results[did]
        return DIDResolutionResult(public_key=None, node_type=None, did_document=None)

    resolver.resolve_full = _resolve_full
    resolver._results = results
    return resolver
