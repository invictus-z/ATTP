"""PendingMessage 单元测试。"""

import time

import pytest

from attp.core.sessions.protocol_node.pending_message import PendingMessage


def _make_pending(**kwargs) -> PendingMessage:
    defaults = {
        "hop": {"Content": "hi"},
        "session_id": "s1",
        "protocol_node_address": "http://localhost:9000",
        "sender_did": "did:sender",
        "sender_node_type": "agent",
        "nonce": "n1",
        "stored_at": time.time(),
    }
    defaults.update(kwargs)
    return PendingMessage(**defaults)


class TestExpiry:
    def test_not_expired_fresh(self):
        msg = _make_pending(stored_at=time.time())
        assert msg.is_expired() is False

    def test_expired_old(self):
        msg = _make_pending(stored_at=time.time() - 600, ttl_seconds=300)
        assert msg.is_expired() is True

    def test_custom_ttl(self):
        msg = _make_pending(stored_at=time.time() - 50, ttl_seconds=100)
        assert msg.is_expired() is False


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        msg = _make_pending(
            node_did="did:test:1",
            identity_verified=True,
            identity_verification_attempted=True,
        )
        d = msg.to_dict()
        restored = PendingMessage.from_dict(d)
        assert restored.session_id == msg.session_id
        assert restored.nonce == msg.nonce
        assert restored.node_did == msg.node_did
        assert restored.identity_verified == msg.identity_verified
        assert restored.identity_verification_attempted == msg.identity_verification_attempted

    def test_from_dict_defaults(self):
        d = {
            "hop": {},
            "session_id": "s1",
            "protocol_node_address": "",
            "sender_did": "",
            "sender_node_type": "agent",
            "nonce": "n1",
            "stored_at": 1000.0,
        }
        msg = PendingMessage.from_dict(d)
        assert msg.ttl_seconds == 300.0
        assert msg.node_did == ""
        assert msg.identity_verified is False
