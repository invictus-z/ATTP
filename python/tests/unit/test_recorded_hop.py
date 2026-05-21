"""RecordedHop 数据模型单元测试。"""

import pytest

from attp.core.message.event import RecordedHop


def _make_hop(**kwargs) -> RecordedHop:
    defaults = {
        "session_id": "s1",
        "sender_did": "did:sender",
        "target_did": "did:target",
        "content": "hello",
        "timestamp": 1000.0,
        "hop_count": [0, 0],
    }
    defaults.update(kwargs)
    return RecordedHop(**defaults)


class TestContentHash:
    def test_deterministic(self):
        hop = _make_hop()
        assert hop.content_hash() == hop.content_hash()

    def test_changes_on_content(self):
        h1 = _make_hop(content="hello")
        h2 = _make_hop(content="world")
        assert h1.content_hash() != h2.content_hash()

    def test_changes_on_sender(self):
        h1 = _make_hop(sender_did="did:a")
        h2 = _make_hop(sender_did="did:b")
        assert h1.content_hash() != h2.content_hash()

    def test_changes_on_target(self):
        h1 = _make_hop(target_did="did:a")
        h2 = _make_hop(target_did="did:b")
        assert h1.content_hash() != h2.content_hash()

    def test_changes_on_hop_count(self):
        h1 = _make_hop(hop_count=[0, 0])
        h2 = _make_hop(hop_count=[1, 0])
        assert h1.content_hash() != h2.content_hash()

    def test_changes_on_timestamp(self):
        h1 = _make_hop(timestamp=1000.0)
        h2 = _make_hop(timestamp=2000.0)
        assert h1.content_hash() != h2.content_hash()

    def test_ignores_sig_content(self):
        h1 = _make_hop(sig_content="")
        h2 = _make_hop(sig_content="signed!")
        assert h1.content_hash() == h2.content_hash()


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        hop = _make_hop(sig_content="sig123")
        d = hop.to_dict()
        restored = RecordedHop.from_dict(d)
        assert restored.session_id == hop.session_id
        assert restored.sender_did == hop.sender_did
        assert restored.target_did == hop.target_did
        assert restored.content == hop.content
        assert restored.timestamp == hop.timestamp
        assert restored.hop_count == hop.hop_count
        assert restored.sig_content == hop.sig_content

    def test_from_dict_missing_sig_content_defaults_empty(self):
        d = {
            "session_id": "s1",
            "sender_did": "did:a",
            "target_did": "did:b",
            "content": "hi",
            "timestamp": 1.0,
            "hop_count": [0, 0],
        }
        hop = RecordedHop.from_dict(d)
        assert hop.sig_content == ""
