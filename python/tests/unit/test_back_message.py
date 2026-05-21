"""BackMessage 签名/验证单元测试。"""

import pytest

from attp.core.message.event import BackMessage, _identity_hash
from tests.fixtures.sample_data import make_back_message


class TestIdentitySignature:
    def test_sign_identity_secp256k1(self, secp256k1_keys):
        private, public = secp256k1_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_identity(private)
        assert msg.sig_identity != ""
        assert msg.verify_identity(public) is True

    def test_sign_identity_p256(self, p256_keys):
        private, public = p256_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_identity(private)
        assert msg.verify_identity(public) is True

    def test_wrong_key_fails(self, secp256k1_keys, p256_keys):
        priv_a, _ = secp256k1_keys
        _, pub_b = p256_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_identity(priv_a)
        assert msg.verify_identity(pub_b) is False

    def test_empty_sig_fails(self, secp256k1_keys):
        _, public = secp256k1_keys
        msg = make_back_message(node_did="did:test:1")
        assert msg.verify_identity(public) is False


class TestContentSignature:
    def test_sign_content_secp256k1(self, secp256k1_keys):
        private, public = secp256k1_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_content(private)
        assert msg.recorded_hop.sig_content != ""
        assert msg.verify_content(public) is True

    def test_sign_content_p256(self, p256_keys):
        private, public = p256_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_content(private)
        assert msg.verify_content(public) is True

    def test_wrong_key_fails(self, secp256k1_keys, p256_keys):
        priv_a, _ = secp256k1_keys
        _, pub_b = p256_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_content(priv_a)
        assert msg.verify_content(pub_b) is False


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self, secp256k1_keys):
        private, _ = secp256k1_keys
        msg = make_back_message(node_did="did:test:1")
        msg.sign_identity(private)
        msg.sign_content(private)
        d = msg.to_dict()
        restored = BackMessage.from_dict(d)
        assert restored.node_did == msg.node_did
        assert restored.nonce == msg.nonce
        assert restored.sig_identity == msg.sig_identity
        assert restored.recorded_hop.content == msg.recorded_hop.content


class TestIdentityHash:
    def test_deterministic(self):
        h1 = _identity_hash("did:test:1", "nonce1")
        h2 = _identity_hash("did:test:1", "nonce1")
        assert h1 == h2

    def test_changes_on_did(self):
        h1 = _identity_hash("did:test:1", "nonce1")
        h2 = _identity_hash("did:test:2", "nonce1")
        assert h1 != h2

    def test_changes_on_nonce(self):
        h1 = _identity_hash("did:test:1", "nonce1")
        h2 = _identity_hash("did:test:1", "nonce2")
        assert h1 != h2
