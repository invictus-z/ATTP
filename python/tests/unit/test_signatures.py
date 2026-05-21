"""加密签名与验签单元测试。"""

import pytest

from attp.core.authentication.signatures import sign_hash, verify_signature


class TestSignHash:
    def test_rsa_sign_returns_nonempty(self, rsa_keys):
        private, _ = rsa_keys
        result = sign_hash("abc123", private)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_secp256k1_sign_returns_nonempty(self, secp256k1_keys):
        private, _ = secp256k1_keys
        result = sign_hash("abc123", private)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_p256_sign_returns_nonempty(self, p256_keys):
        private, _ = p256_keys
        result = sign_hash("abc123", private)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unsupported_key_returns_empty(self):
        assert sign_hash("abc123", "not_a_key") == ""


class TestVerifySignature:
    def test_rsa_roundtrip(self, rsa_keys):
        private, public = rsa_keys
        sig = sign_hash("test_hash", private)
        assert verify_signature("test_hash", sig, public) is True

    def test_secp256k1_roundtrip(self, secp256k1_keys):
        private, public = secp256k1_keys
        sig = sign_hash("test_hash", private)
        assert verify_signature("test_hash", sig, public) is True

    def test_p256_roundtrip(self, p256_keys):
        private, public = p256_keys
        sig = sign_hash("test_hash", private)
        assert verify_signature("test_hash", sig, public) is True

    def test_wrong_key_fails(self, rsa_keys, p256_keys):
        _, rsa_pub = rsa_keys
        p256_priv, _ = p256_keys
        sig = sign_hash("test_hash", p256_priv)
        assert verify_signature("test_hash", sig, rsa_pub) is False

    def test_tampered_hash_fails(self, secp256k1_keys):
        private, public = secp256k1_keys
        sig = sign_hash("original_hash", private)
        assert verify_signature("tampered_hash", sig, public) is False

    def test_empty_signature_fails(self, secp256k1_keys):
        _, public = secp256k1_keys
        assert verify_signature("test_hash", "", public) is False

    def test_corrupt_b64_fails(self, secp256k1_keys):
        _, public = secp256k1_keys
        assert verify_signature("test_hash", "!!!not-base64!!!", public) is False

    def test_unsupported_public_key_type(self):
        assert verify_signature("test_hash", "sig", "not_a_key") is False
