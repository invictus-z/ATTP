"""中间件单元测试 — _validate_back_message + intercept_record。"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from attp.core.message.event import BackMessage, RecordedHop
from attp.core.sessions.protocol_node.pending_message import PendingMessage
from attp.core.sessions.protocol_node.session import ProtocolSession
from attp.core.sessions.protocol_node.manager import ProtocolSessionManager
from attp.protocol_node.engine.middleware import (
    _validate_back_message,
    intercept_record,
    BEHAVIOR_TYPE_MAP,
)
from tests.fixtures.sample_data import (
    make_back_message,
    make_session_id,
    make_nonce,
    TEST_AGENT_DID,
    TEST_TOOL_DID,
    TEST_USER_DID,
)


def _make_valid_back_msg(**overrides) -> BackMessage:
    defaults = {
        "node_did": TEST_AGENT_DID,
        "nonce": make_nonce(),
        "session_id": make_session_id(),
        "sender_did": TEST_USER_DID,
        "target_did": TEST_AGENT_DID,
        "content": "hello",
        "hop_count": [0, 0],
    }
    defaults.update(overrides)
    msg = make_back_message(**defaults)
    msg.sig_identity = "fake_sig_identity"
    msg.recorded_hop.sig_content = "fake_sig_content"
    return msg


class TestValidateBackMessage:
    def test_all_valid(self):
        msg = _make_valid_back_msg()
        ok, err = _validate_back_message(msg)
        assert ok is True
        assert err == ""

    def test_empty_node_did(self):
        msg = _make_valid_back_msg(node_did="")
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "node_did" in err

    def test_empty_nonce(self):
        msg = _make_valid_back_msg()
        msg.nonce = ""
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "nonce" in err

    def test_empty_sig_identity(self):
        msg = _make_valid_back_msg()
        msg.sig_identity = ""
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "sig_identity" in err

    def test_empty_session_id(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.session_id = ""
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "session_id" in err

    def test_empty_sender_did(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.sender_did = ""
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "sender_did" in err

    def test_empty_target_did(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.target_did = ""
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "target_did" in err

    def test_hop_count_not_list(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.hop_count = "bad"
        ok, err = _validate_back_message(msg)
        assert ok is False

    def test_hop_count_wrong_length(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.hop_count = [1]
        ok, err = _validate_back_message(msg)
        assert ok is False

    def test_hop_count_negative(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.hop_count = [-1, 0]
        ok, err = _validate_back_message(msg)
        assert ok is False

    def test_timestamp_zero(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.timestamp = 0
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "timestamp" in err

    def test_empty_sig_content(self):
        msg = _make_valid_back_msg()
        msg.recorded_hop.sig_content = ""
        ok, err = _validate_back_message(msg)
        assert ok is False
        assert "sig_content" in err


class TestInterceptRecordBranchA:
    @pytest.mark.asyncio
    async def test_stores_pending(self, mock_did_resolver, agent_keys, session_manager):
        _, agent_pub = agent_keys
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        malicious_detector = AsyncMock()

        nonce = make_nonce()
        session_id = make_session_id()
        msg = _make_valid_back_msg(
            node_did=TEST_AGENT_DID,
            nonce=nonce,
            session_id=session_id,
        )
        msg.sign_identity(agent_keys[0])
        msg.sign_content(agent_keys[0])

        result = await intercept_record(
            msg, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "stored"
        assert result.error is None

        session = session_manager.get(session_id)
        assert session is not None
        pending = session.get_pending_message(nonce)
        assert pending is not None

    @pytest.mark.asyncio
    async def test_identity_verified_true(self, mock_did_resolver, agent_keys, session_manager):
        _, agent_pub = agent_keys
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        malicious_detector = AsyncMock()

        nonce = make_nonce()
        msg = _make_valid_back_msg(node_did=TEST_AGENT_DID, nonce=nonce)
        msg.sign_identity(agent_keys[0])

        result = await intercept_record(
            msg, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "stored"

        session = session_manager.get(msg.recorded_hop.session_id)
        pending = session.get_pending_message(nonce)
        assert pending.identity_verified is True

    @pytest.mark.asyncio
    async def test_identity_verified_false(self, mock_did_resolver, agent_keys, p256_keys, session_manager):
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        malicious_detector = AsyncMock()

        wrong_priv = p256_keys[0]
        nonce = make_nonce()
        msg = _make_valid_back_msg(node_did=TEST_AGENT_DID, nonce=nonce)
        msg.sign_identity(wrong_priv)

        result = await intercept_record(
            msg, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "stored"

        session = session_manager.get(msg.recorded_hop.session_id)
        pending = session.get_pending_message(nonce)
        assert pending.identity_verified is False


class TestInterceptRecordBranchB:
    @pytest.mark.asyncio
    async def test_verified_agent_to_tool(self, mock_did_resolver, agent_keys, tool_keys, session_manager):
        agent_priv, agent_pub = agent_keys
        tool_priv, tool_pub = tool_keys
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        tracer.verify_back_propagation = MagicMock(return_value=(True, ""))
        malicious_detector = AsyncMock()
        malicious_detector.evaluate_dual_back_prop = AsyncMock(return_value=None)

        nonce = make_nonce()
        session_id = make_session_id()

        bp1 = _make_valid_back_msg(
            node_did=TEST_AGENT_DID,
            nonce=nonce,
            session_id=session_id,
            sender_did=TEST_USER_DID,
            target_did=TEST_TOOL_DID,
            hop_count=[0, 1],
        )
        bp1.sign_identity(agent_priv)
        bp1.sign_content(agent_priv)

        result1 = await intercept_record(
            bp1, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result1.status == "stored"

        bp2 = _make_valid_back_msg(
            node_did=TEST_TOOL_DID,
            nonce=nonce,
            session_id=session_id,
            sender_did=TEST_USER_DID,
            target_did=TEST_TOOL_DID,
            hop_count=[0, 1],
        )
        bp2.sign_identity(tool_priv)
        bp2.sign_content(tool_priv)

        result2 = await intercept_record(
            bp2, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result2.status == "verified"
        assert result2.behavior_type == "A2T"

    @pytest.mark.asyncio
    async def test_verified_user_to_agent(self, mock_did_resolver, user_keys, agent_keys, session_manager):
        user_priv, user_pub = user_keys
        agent_priv, agent_pub = agent_keys
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        tracer.verify_back_propagation = MagicMock(return_value=(True, ""))
        malicious_detector = AsyncMock()
        malicious_detector.evaluate_dual_back_prop = AsyncMock(return_value=None)

        nonce = make_nonce()
        session_id = make_session_id()

        bp1 = _make_valid_back_msg(
            node_did=TEST_USER_DID,
            nonce=nonce,
            session_id=session_id,
            sender_did=TEST_USER_DID,
            target_did=TEST_AGENT_DID,
            hop_count=[0, 0],
        )
        bp1.sign_identity(user_priv)
        bp1.sign_content(user_priv)

        await intercept_record(bp1, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp2 = _make_valid_back_msg(
            node_did=TEST_AGENT_DID,
            nonce=nonce,
            session_id=session_id,
            sender_did=TEST_USER_DID,
            target_did=TEST_AGENT_DID,
            hop_count=[0, 0],
        )
        bp2.sign_identity(agent_priv)
        bp2.sign_content(agent_priv)

        result2 = await intercept_record(
            bp2, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result2.status == "verified"
        assert result2.behavior_type == "U2A"

    @pytest.mark.asyncio
    async def test_malicious_detected(self, mock_did_resolver, agent_keys, session_manager):
        from attp.protocol_node.engine.malicious_detector import (
            MaliciousNodeReport,
            EvidenceType,
        )

        tracer = MagicMock()
        tracer.key_store = MagicMock()
        tracer.save_malicious_report = AsyncMock()

        report = MaliciousNodeReport(
            malicious_dids=[TEST_AGENT_DID],
            evidence_type=EvidenceType.SAME_DID_DUPLICATE,
            evidence_description="test",
            session_id="s1",
            nonce="n1",
            timestamp=time.time(),
            raw_evidence={},
        )
        malicious_detector = AsyncMock()
        malicious_detector.evaluate_dual_back_prop = AsyncMock(return_value=report)

        nonce = make_nonce()
        session_id = make_session_id()

        bp1 = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=session_id,
        )
        bp1.sign_identity(agent_keys[0])
        bp1.sign_content(agent_keys[0])
        await intercept_record(bp1, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp2 = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=session_id,
        )
        bp2.sign_identity(agent_keys[0])
        bp2.sign_content(agent_keys[0])

        result = await intercept_record(
            bp2, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "malicious"
        assert result.malicious_report is not None

    @pytest.mark.asyncio
    async def test_did_resolution_fails(self, agent_keys, session_manager):
        from attp.core.authentication.did_resolver import DIDResolutionResult

        mock_resolver = AsyncMock()
        mock_resolver.resolve_full = AsyncMock(
            return_value=DIDResolutionResult(public_key=None, node_type=None, did_document=None)
        )

        tracer = MagicMock()
        tracer.key_store = MagicMock()
        malicious_detector = AsyncMock()

        msg = _make_valid_back_msg(node_did="did:wba:unknown%3A9999:agent:bad")
        result = await intercept_record(
            msg, mock_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "error"
        assert "did_resolution_failed" in result.error

    @pytest.mark.asyncio
    async def test_missing_type_field(self, agent_keys, session_manager):
        from attp.core.authentication.did_resolver import DIDResolutionResult

        mock_resolver = AsyncMock()
        mock_resolver.resolve_full = AsyncMock(
            return_value=DIDResolutionResult(
                public_key=agent_keys[1],
                node_type=None,
                did_document={},
            )
        )

        tracer = MagicMock()
        tracer.key_store = MagicMock()
        malicious_detector = AsyncMock()

        msg = _make_valid_back_msg(node_did="did:test:1")
        result = await intercept_record(
            msg, mock_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "error"
        assert "missing_type_field" in result.error

    @pytest.mark.asyncio
    async def test_back_propagation_fails(self, mock_did_resolver, agent_keys, tool_keys, session_manager):
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        tracer.verify_back_propagation = MagicMock(return_value=(False, "tampered"))
        malicious_detector = AsyncMock()
        malicious_detector.evaluate_dual_back_prop = AsyncMock(return_value=None)

        nonce = make_nonce()
        session_id = make_session_id()

        bp1 = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=session_id,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID, hop_count=[0, 1],
        )
        bp1.sign_identity(agent_keys[0])
        await intercept_record(bp1, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp2 = _make_valid_back_msg(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=session_id,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID, hop_count=[0, 1],
        )
        bp2.sign_identity(tool_keys[0])

        result = await intercept_record(
            bp2, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "error"
        assert "back_propagation" in result.error

    @pytest.mark.asyncio
    async def test_hop_zero_not_u2a(self, mock_did_resolver, agent_keys, tool_keys, session_manager):
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        tracer.verify_back_propagation = MagicMock(return_value=(True, ""))
        malicious_detector = AsyncMock()
        malicious_detector.evaluate_dual_back_prop = AsyncMock(return_value=None)

        nonce = make_nonce()
        session_id = make_session_id()

        bp1 = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce, session_id=session_id,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID, hop_count=[0, 0],
        )
        bp1.sign_identity(agent_keys[0])
        await intercept_record(bp1, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp2 = _make_valid_back_msg(
            node_did=TEST_TOOL_DID, nonce=nonce, session_id=session_id,
            sender_did=TEST_AGENT_DID, target_did=TEST_TOOL_DID, hop_count=[0, 0],
        )
        bp2.sign_identity(tool_keys[0])

        result = await intercept_record(
            bp2, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "error"
        assert "hop_zero_must_be_u2a" in result.error

    @pytest.mark.asyncio
    async def test_hop_count_a2a_violation(self, mock_did_resolver, agent_keys, session_manager):
        tracer = MagicMock()
        tracer.key_store = MagicMock()
        tracer.verify_back_propagation = MagicMock(return_value=(True, ""))
        malicious_detector = AsyncMock()
        malicious_detector.evaluate_dual_back_prop = AsyncMock(return_value=None)

        nonce1 = make_nonce()
        nonce2 = make_nonce()
        session_id = make_session_id()

        bp1_u2a = _make_valid_back_msg(
            node_did=TEST_USER_DID, nonce=nonce1, session_id=session_id,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID, hop_count=[0, 0],
        )
        bp1_u2a.sign_identity(agent_keys[0])
        await intercept_record(bp1_u2a, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp2_u2a = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce1, session_id=session_id,
            sender_did=TEST_USER_DID, target_did=TEST_AGENT_DID, hop_count=[0, 0],
        )
        bp2_u2a.sign_identity(agent_keys[0])
        await intercept_record(bp2_u2a, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp1_a2a = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce2, session_id=session_id,
            sender_did=TEST_AGENT_DID, target_did="did:wba:localhost%3A8000:agent:agent02",
            hop_count=[3, 0],
        )
        bp1_a2a.sign_identity(agent_keys[0])
        await intercept_record(bp1_a2a, mock_did_resolver, tracer, session_manager, malicious_detector)

        bp2_a2a = _make_valid_back_msg(
            node_did=TEST_AGENT_DID, nonce=nonce2, session_id=session_id,
            sender_did=TEST_AGENT_DID, target_did="did:wba:localhost%3A8000:agent:agent02",
            hop_count=[3, 0],
        )
        bp2_a2a.sign_identity(agent_keys[0])

        result = await intercept_record(
            bp2_a2a, mock_did_resolver, tracer, session_manager, malicious_detector,
        )
        assert result.status == "error"
        assert "hop_count_violation" in result.error
