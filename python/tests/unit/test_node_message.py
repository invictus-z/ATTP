"""NodeMessage 签名/验证单元测试。"""

import pytest

from attp.core.message.event import NodeMessage
from tests.fixtures.sample_data import make_node_message


class TestContentSignature:
    def test_sign_and_verify(self, secp256k1_keys):
        private, public = secp256k1_keys
        msg = make_node_message()
        msg.sign_content(private)
        assert msg.recorded_hop.sig_content != ""
        assert msg.verify_content(public) is True

    def test_wrong_key_fails(self, secp256k1_keys, p256_keys):
        priv_a, _ = secp256k1_keys
        _, pub_b = p256_keys
        msg = make_node_message()
        msg.sign_content(priv_a)
        assert msg.verify_content(pub_b) is False

    def test_empty_sig_fails(self, secp256k1_keys):
        _, public = secp256k1_keys
        msg = make_node_message()
        assert msg.verify_content(public) is False


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self, secp256k1_keys):
        private, _ = secp256k1_keys
        msg = make_node_message()
        msg.sign_content(private)
        d = msg.to_dict()
        restored = NodeMessage.from_dict(d)
        assert restored.protocol_url == msg.protocol_url
        assert restored.nonce == msg.nonce
        assert restored.recorded_hop.content == msg.recorded_hop.content
        assert restored.recorded_hop.sig_content == msg.recorded_hop.sig_content
