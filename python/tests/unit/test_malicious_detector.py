"""恶意检测器单元测试 — 双重回传 + 单次回传决策树。"""

import time
from unittest.mock import AsyncMock

import pytest

from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.core.message.event import BackMessage
from attp.core.sessions.protocol_node.pending_message import PendingMessage
from attp.core.sessions.protocol_node.session import ProtocolSession
from attp.protocol_node.engine.malicious_detector import (
    MaliciousNodeDetector,
    MaliciousNodeReport,
    EvidenceType,
)
from tests.fixtures.sample_data import (
    make_back_message,
    make_session_id,
    make_nonce,
    TEST_AGENT_DID,
    TEST_TOOL_DID,
    TEST_USER_DID,
    TEST_PNA,
)


def _make_pending(
    node_did=TEST_AGENT_DID,
    sender_did=TEST_USER_DID,
    identity_verified=True,
    session_id=None,
    nonce=None,
    content="hello",
    hop_count=None,
    sender_node_type="agent",
    target_did=TEST_TOOL_DID,
    private_key_for_sig=None,
) -> PendingMessage:
    sid = session_id or make_session_id()
    n = nonce or make_nonce()
    hc = hop_count or [0, 0]
    ts = time.time()

    hop = {
        "node_did": sender_did,
        "target_did": target_did,
        "Content": content,
        "Timestamp": ts,
        "Hop_Count": hc,
        "Signature": "",
        "session_id": sid,
        "protocol_node_address": TEST_PNA,
    }

    if private_key_for_sig:
        from attp.core.authentication.signatures import sign_hash
        from attp.core.message.event import RecordedHop

        rh = RecordedHop(
            session_id=sid, sender_did=sender_did, target_did=target_did,
            content=content, timestamp=ts, hop_count=hc,
        )
        hop["Signature"] = sign_hash(rh.content_hash(), private_key_for_sig)

    return PendingMessage(
        hop=hop,
        session_id=sid,
        protocol_node_address=TEST_PNA,
        sender_did=sender_did,
        sender_node_type=sender_node_type,
        nonce=n,
        stored_at=time.time(),
        node_did=node_did,
        identity_verified=identity_verified,
        identity_verification_attempted=True,
    )


def _make_bp2(
    node_did=TEST_TOOL_DID,
    sender_did=TEST_USER_DID,
    target_did=TEST_TOOL_DID,
    session_id=None,
    nonce=None,
    content="hello",
    hop_count=None,
    private_key=None,
) -> BackMessage:
    sid = session_id or make_session_id()
    n = nonce or make_nonce()
    msg = make_back_message(
        node_did=node_did,
        nonce=n,
        session_id=sid,
        sender_did=sender_did,
        target_did=target_did,
        content=content,
        hop_count=hop_count or [0, 0],
    )
    if private_key:
        msg.sign_content(private_key)
    return msg


class TestDualBackProp:
    @pytest.mark.asyncio
    async def test_bp1_identity_tampering_with_trusted_list(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = ["did:trusted:1"]

        nonce = make_nonce()
        sid = make_session_id()
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=False,
            session_id=sid, nonce=nonce,
        )
        bp2 = _make_bp2(session_id=sid, nonce=nonce)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.IDENTITY_TAMPERING
        assert "did:trusted:1" in report.malicious_dids

    @pytest.mark.asyncio
    async def test_bp1_identity_tampering_no_trusted_list(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=False,
            session_id=sid, nonce=nonce,
        )
        bp2 = _make_bp2(session_id=sid, nonce=nonce)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.IDENTITY_TAMPERING
        assert TEST_AGENT_DID in report.malicious_dids

    @pytest.mark.asyncio
    async def test_trusted_list_violation(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = ["did:trusted:1"]

        nonce = make_nonce()
        sid = make_session_id()
        stored = _make_pending(
            node_did="did:other:1", identity_verified=True,
            session_id=sid, nonce=nonce,
        )
        bp2 = _make_bp2(session_id=sid, nonce=nonce)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.TRUSTED_LIST_VIOLATION

    @pytest.mark.asyncio
    async def test_bp2_did_resolution_fails(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            session_id=sid, nonce=nonce, target_did=TEST_TOOL_DID,
        )
        bp2 = _make_bp2(
            node_did="did:wba:unknown%3A9999:agent:bad",
            session_id=sid, nonce=nonce,
        )

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.IDENTITY_TAMPERING
        assert TEST_TOOL_DID in report.malicious_dids

    @pytest.mark.asyncio
    async def test_bp2_identity_verify_fails(self, mock_did_resolver, p256_keys):
        wrong_priv, _ = p256_keys
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            session_id=sid, nonce=nonce, target_did=TEST_TOOL_DID,
        )

        bp2 = _make_bp2(node_did=TEST_TOOL_DID, session_id=sid, nonce=nonce)
        bp2.sign_identity(wrong_priv)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.IDENTITY_TAMPERING

    @pytest.mark.asyncio
    async def test_same_did_duplicate(self, mock_did_resolver, agent_keys):
        agent_priv, _ = agent_keys
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            session_id=sid, nonce=nonce,
            private_key_for_sig=agent_priv,
        )

        bp2 = _make_bp2(
            node_did=TEST_AGENT_DID, session_id=sid, nonce=nonce,
            private_key=agent_priv,
        )
        bp2.sign_identity(agent_priv)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.SAME_DID_DUPLICATE

    @pytest.mark.asyncio
    async def test_content_tampering_invalid_sig(self, mock_did_resolver, user_keys, tool_keys):
        user_priv, user_pub = user_keys
        tool_priv, _ = tool_keys
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()
        # Content signed with wrong key (not the sender's key)
        from tests.fixtures.crypto_helpers import generate_secp256k1_keypair
        wrong_priv, _ = generate_secp256k1_keypair()
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            session_id=sid, nonce=nonce,
            sender_did=TEST_USER_DID,
            private_key_for_sig=wrong_priv,
        )

        bp2 = _make_bp2(
            node_did=TEST_TOOL_DID, session_id=sid, nonce=nonce,
            sender_did=TEST_USER_DID,
        )
        bp2.sign_identity(tool_priv)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.CONTENT_TAMPERING

    @pytest.mark.asyncio
    async def test_cross_verify_succeeds(self, mock_did_resolver, user_keys, tool_keys):
        user_priv, user_pub = user_keys
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()

        # Both signed by the sender (user)
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            session_id=sid, nonce=nonce,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID,
            private_key_for_sig=user_priv,
        )

        bp2 = _make_bp2(
            node_did=TEST_TOOL_DID, session_id=sid, nonce=nonce,
            sender_did=TEST_USER_DID, target_did=TEST_TOOL_DID,
            private_key=user_priv,
        )
        bp2.sign_identity(tool_keys[0])

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is None

    @pytest.mark.asyncio
    async def test_indistinguishable_pair(self, mock_did_resolver, user_keys, tool_keys):
        user_priv, user_pub = user_keys
        tool_priv, _ = tool_keys
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        nonce = make_nonce()
        sid = make_session_id()

        # BP1 content signed by sender (user)
        stored = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            session_id=sid, nonce=nonce,
            sender_did=TEST_USER_DID,
            private_key_for_sig=user_priv,
        )

        # BP2 content signed by different key (tool) - cross verify fails
        bp2 = _make_bp2(
            node_did=TEST_TOOL_DID, session_id=sid, nonce=nonce,
            sender_did=TEST_USER_DID,
            private_key=tool_priv,
        )
        bp2.sign_identity(tool_priv)

        report = await detector.evaluate_dual_back_prop(stored, bp2, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.INDISTINGUISHABLE_PAIR


class TestSingleBackProp:
    @pytest.mark.asyncio
    async def test_identity_tampering_with_trusted_list(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = ["did:trusted:1"]

        pending = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=False,
        )

        report = await detector.evaluate_single_back_prop(pending, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.IDENTITY_TAMPERING
        assert "did:trusted:1" in report.malicious_dids

    @pytest.mark.asyncio
    async def test_identity_tampering_no_trusted_list(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())

        pending = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=False,
        )

        report = await detector.evaluate_single_back_prop(pending, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.IDENTITY_TAMPERING
        assert TEST_AGENT_DID in report.malicious_dids

    @pytest.mark.asyncio
    async def test_trusted_list_violation(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = ["did:trusted:1"]

        pending = _make_pending(
            node_did="did:other:1", identity_verified=True,
        )

        report = await detector.evaluate_single_back_prop(pending, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.TRUSTED_LIST_VIOLATION

    @pytest.mark.asyncio
    async def test_no_subsequent_no_report(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = [TEST_AGENT_DID]

        pending = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
        )

        report = await detector.evaluate_single_back_prop(pending, session)
        assert report is None

    @pytest.mark.asyncio
    async def test_subsequent_same_identity_no_report(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = [TEST_AGENT_DID]

        pending1 = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            nonce="n1",
        )
        session.store_pending_message("n1", pending1)

        pending2 = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            nonce="n2",
        )
        session.store_pending_message("n2", pending2)

        report = await detector.evaluate_single_back_prop(pending1, session)
        assert report is None

    @pytest.mark.asyncio
    async def test_subsequent_different_identity_no_propagation(self, mock_did_resolver):
        detector = MaliciousNodeDetector(mock_did_resolver)
        session = ProtocolSession(key=make_session_id())
        session.trusted_did_list = [TEST_AGENT_DID]

        pending1 = _make_pending(
            node_did=TEST_AGENT_DID, identity_verified=True,
            nonce="n1", target_did=TEST_TOOL_DID,
        )
        session.store_pending_message("n1", pending1)

        pending2 = _make_pending(
            node_did=TEST_TOOL_DID, identity_verified=True,
            nonce="n2",
        )
        session.store_pending_message("n2", pending2)

        report = await detector.evaluate_single_back_prop(pending1, session)
        assert report is not None
        assert report.evidence_type == EvidenceType.NO_PROPAGATION
        assert TEST_TOOL_DID in report.malicious_dids
