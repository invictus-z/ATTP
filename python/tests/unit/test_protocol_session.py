"""协议会话单元测试。"""

import time

import pytest

from attp.core.sessions.protocol_node.session import ProtocolSession
from attp.core.sessions.protocol_node.pending_message import PendingMessage


def _make_pending(nonce="n1", node_did="did:test:1", identity_verified=True, ttl=300.0) -> PendingMessage:
    return PendingMessage(
        hop={"node_did": "did:sender", "target_did": "did:target", "Content": "hi",
             "Timestamp": time.time(), "Hop_Count": [0, 0], "Signature": "sig",
             "session_id": "s1", "protocol_node_address": "http://localhost:9000"},
        session_id="s1",
        protocol_node_address="http://localhost:9000",
        sender_did="did:sender",
        sender_node_type="agent",
        nonce=nonce,
        stored_at=time.time(),
        ttl_seconds=ttl,
        node_did=node_did,
        identity_verified=identity_verified,
        identity_verification_attempted=True,
    )


class TestPendingMessages:
    def test_store_and_get(self):
        session = ProtocolSession(key="s1")
        msg = _make_pending(nonce="n1")
        session.store_pending_message("n1", msg)
        result = session.get_pending_message("n1")
        assert result is not None
        assert result.nonce == "n1"

    def test_get_not_found(self):
        session = ProtocolSession(key="s1")
        assert session.get_pending_message("nonexistent") is None

    def test_get_expired_removed(self):
        session = ProtocolSession(key="s1")
        msg = _make_pending(nonce="n1", ttl=0.001)
        msg.stored_at = time.time() - 1
        session.store_pending_message("n1", msg)
        assert session.get_pending_message("n1") is None

    def test_remove(self):
        session = ProtocolSession(key="s1")
        session.store_pending_message("n1", _make_pending(nonce="n1"))
        session.remove_pending_message("n1")
        assert session.get_pending_message("n1") is None

    def test_pop_expired(self):
        session = ProtocolSession(key="s1")
        expired = _make_pending(nonce="n1", ttl=0.001)
        expired.stored_at = time.time() - 1
        fresh = _make_pending(nonce="n2", ttl=300)
        session.store_pending_message("n1", expired)
        session.store_pending_message("n2", fresh)

        result = session.pop_expired_pending_messages()
        assert len(result) == 1
        assert result[0][0] == "n1"
        assert session.get_pending_message("n2") is not None


class TestCompleteVerification:
    def test_updates_hop_count_and_trusted_list(self):
        session = ProtocolSession(key="s1")
        msg = _make_pending(nonce="n1")
        session.store_pending_message("n1", msg)

        session.complete_verification(
            nonce="n1", hop_count=[0, 0], trusted_did="did:target",
        )
        assert session.get_last_completed_hop_count() == [0, 0]
        assert session.get_latest_trusted_did() == "did:target"
        assert session.get_pending_message("n1") is None


class TestTrustedList:
    def test_add_and_get_latest(self):
        session = ProtocolSession(key="s1")
        session.add_trusted_did("did:a")
        session.add_trusted_did("did:b")
        assert session.get_latest_trusted_did() == "did:b"

    def test_get_list_copy(self):
        session = ProtocolSession(key="s1")
        session.add_trusted_did("did:a")
        lst = session.get_trusted_did_list()
        lst.append("did:extra")
        assert "did:extra" not in session.get_trusted_did_list()

    def test_clear(self):
        session = ProtocolSession(key="s1")
        session.add_trusted_did("did:a")
        session.clear_trusted_list()
        assert session.get_trusted_did_list() == []

    def test_get_latest_empty(self):
        session = ProtocolSession(key="s1")
        assert session.get_latest_trusted_did() is None


class TestSubsequentActivity:
    def test_has_subsequent_with_other_pending(self):
        session = ProtocolSession(key="s1")
        session.store_pending_message("n1", _make_pending(nonce="n1"))
        session.store_pending_message("n2", _make_pending(nonce="n2"))
        assert session.has_subsequent_activity_after("n1") is True

    def test_no_subsequent(self):
        session = ProtocolSession(key="s1")
        session.store_pending_message("n1", _make_pending(nonce="n1"))
        assert session.has_subsequent_activity_after("n1") is False

    def test_has_subsequent_different_verified_identity(self):
        session = ProtocolSession(key="s1")
        session.store_pending_message("n1", _make_pending(nonce="n1", node_did="did:a", identity_verified=True))
        session.store_pending_message("n2", _make_pending(nonce="n2", node_did="did:b", identity_verified=True))
        assert session.has_subsequent_with_different_verified_identity("n1", "did:a") is True

    def test_same_identity_not_different(self):
        session = ProtocolSession(key="s1")
        session.store_pending_message("n1", _make_pending(nonce="n1", node_did="did:a", identity_verified=True))
        session.store_pending_message("n2", _make_pending(nonce="n2", node_did="did:a", identity_verified=True))
        assert session.has_subsequent_with_different_verified_identity("n1", "did:a") is False


class TestAnalysisState:
    def test_increment_report_count(self):
        session = ProtocolSession(key="s1")
        assert session.increment_report_count() == 1
        assert session.increment_report_count() == 2

    def test_reset_report_count(self):
        session = ProtocolSession(key="s1")
        session.increment_report_count()
        session.reset_report_count()
        state = session.get_analysis_state()
        assert state["report_count"] == 0

    def test_set_get_intent(self):
        session = ProtocolSession(key="s1")
        session.set_intent({"action": "query"})
        assert session.get_intent() == {"action": "query"}

    def test_get_intent_none(self):
        session = ProtocolSession(key="s1")
        assert session.get_intent() is None
