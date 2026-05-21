"""加密辅助工具 — 生成测试用密钥对和 DID 文档。"""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
from cryptography.hazmat.primitives import hashes, serialization


def generate_rsa_keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def generate_secp256k1_keypair():
    private = ec.generate_private_key(ec.SECP256K1())
    return private, private.public_key()


def generate_p256_keypair():
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


def _ec_pub_to_jwk(pub_key: ec.EllipticCurvePublicKey) -> dict:
    nums = pub_key.public_numbers()
    curve_name = None
    for name, curve in {
        "secp256k1": ec.SECP256K1(),
        "P-256": ec.SECP256R1(),
        "P-384": ec.SECP384R1(),
        "P-521": ec.SECP521R1(),
    }.items():
        if isinstance(pub_key.curve, type(curve)) and pub_key.curve.key_size == curve.key_size:
            curve_name = name
            break
    if curve_name is None:
        curve_name = pub_key.curve.name

    byte_len = (pub_key.curve.key_size + 7) // 8
    return {
        "kty": "EC",
        "crv": curve_name,
        "x": base64.urlsafe_b64encode(nums.x.to_bytes(byte_len, "big")).rstrip(b"=").decode(),
        "y": base64.urlsafe_b64encode(nums.y.to_bytes(byte_len, "big")).rstrip(b"=").decode(),
    }


def build_did_document(
    did: str,
    public_key: ec.EllipticCurvePublicKey,
    node_type: str = "agent",
    key_id: str = "key-1",
    key_type: str | None = None,
) -> dict[str, Any]:
    if key_type is None:
        curve_name = public_key.curve.name
        if curve_name == "secp256k1":
            key_type = "EcdsaSecp256k1VerificationKey2019"
        else:
            key_type = "EcdsaSecp256r1VerificationKey2019"

    jwk = _ec_pub_to_jwk(public_key)
    return {
        "@context": ["https://www.w3.org/ns/did/v1"],
        "id": did,
        "verificationMethod": [
            {
                "id": f"{did}#{key_id}",
                "type": key_type,
                "controller": did,
                "publicKeyJwk": jwk,
            }
        ],
        "authentication": [f"{did}#{key_id}"],
        "service": [
            {
                "id": f"{did}#attp-type",
                "type": "ATTPNodeType",
                "serviceEndpoint": f"attp:type:{node_type}",
            }
        ],
    }


def build_did_resolution_result(
    did: str,
    public_key: ec.EllipticCurvePublicKey,
    node_type: str = "agent",
):
    from attp.core.authentication.did_resolver import DIDResolutionResult

    did_doc = build_did_document(did, public_key, node_type)
    return DIDResolutionResult(
        public_key=public_key,
        node_type=node_type,
        did_document=did_doc,
        from_cache=False,
    )
