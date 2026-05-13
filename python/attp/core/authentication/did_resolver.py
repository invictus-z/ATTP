"""DID 文档解析器 — 从 ANP 迁移的 DID 发现、公钥提取、节点类型识别。

提供带 TTL 缓存和重试机制的 DID 解析能力，不再依赖 anp.authentication。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union

import aiohttp
import base58
from cryptography.hazmat.primitives.asymmetric import ec, ed25519

from .keys import KeyStore

logger = logging.getLogger(__name__)

# --- 常量 ---

ATTP_NODE_TYPE_SERVICE = "ATTPNodeType"
VALID_NODE_TYPES = {"agent", "tool", "user"}

CURVE_MAPPING: dict[str, ec.EllipticCurve] = {
    "secp256k1": ec.SECP256K1(),
    "P-256": ec.SECP256R1(),
    "P-384": ec.SECP384R1(),
    "P-521": ec.SECP521R1(),
}

# --- 数据类 ---


@dataclass
class DIDResolutionResult:
    """DID 解析完整结果。"""

    public_key: object | None = None
    node_type: str | None = None
    did_document: dict | None = None
    from_cache: bool = False


@dataclass
class _CacheEntry:
    """DID 文档缓存条目。"""

    did_document: dict
    resolved_at: float


# --- 从 ANP 提取的辅助函数 ---


def _extract_ec_public_key_from_jwk(jwk: dict) -> ec.EllipticCurvePublicKey:
    """从 JWK 格式提取 EC 公钥。"""
    if jwk.get("kty") != "EC":
        raise ValueError("Invalid JWK: kty must be EC")

    crv = jwk.get("crv")
    if not crv:
        raise ValueError("Missing curve parameter in JWK")

    curve = CURVE_MAPPING.get(crv)
    if curve is None:
        raise ValueError(
            f"Unsupported curve: {crv}. "
            f"Supported: {', '.join(CURVE_MAPPING.keys())}"
        )

    x = int.from_bytes(
        base64.urlsafe_b64decode(jwk["x"] + "=" * (-len(jwk["x"]) % 4)), "big"
    )
    y = int.from_bytes(
        base64.urlsafe_b64decode(jwk["y"] + "=" * (-len(jwk["y"]) % 4)), "big"
    )
    return ec.EllipticCurvePublicNumbers(x, y, curve).public_key()


def _extract_ed25519_public_key_from_multibase(
    multibase: str,
) -> ed25519.Ed25519PublicKey:
    """从 multibase 格式提取 Ed25519 公钥。"""
    if not multibase.startswith("z"):
        raise ValueError("Unsupported multibase encoding")
    key_bytes = base58.b58decode(multibase[1:])
    if len(key_bytes) == 34 and key_bytes[:2] == b"\xed\x01":
        key_bytes = key_bytes[2:]
    return ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)


def _extract_ed25519_public_key_from_base58(
    base58_key: str,
) -> ed25519.Ed25519PublicKey:
    """从 base58 格式提取 Ed25519 公钥。"""
    key_bytes = base58.b58decode(base58_key)
    return ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)


def _extract_secp256k1_public_key_from_multibase(
    multibase: str,
) -> ec.EllipticCurvePublicKey:
    """从 multibase 格式提取 secp256k1 公钥。"""
    if not multibase.startswith("z"):
        raise ValueError(
            "Unsupported multibase encoding format, must start with 'z' (base58btc)"
        )
    key_bytes = base58.b58decode(multibase[1:])
    if len(key_bytes) != 33:
        raise ValueError("Invalid secp256k1 public key length")
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), key_bytes)


def _extract_public_key(
    verification_method: dict,
) -> Union[ec.EllipticCurvePublicKey, ed25519.Ed25519PublicKey]:
    """从 verificationMethod 提取公钥。

    支持: EcdsaSecp256k1VerificationKey2019, EcdsaSecp256r1VerificationKey2019,
          Ed25519VerificationKey2020/2018, Multikey, JsonWebKey2020
    """
    method_type = verification_method.get("type")
    if not method_type:
        raise ValueError("Verification method missing 'type' field")

    if method_type == "EcdsaSecp256k1VerificationKey2019":
        if "publicKeyJwk" in verification_method:
            jwk = verification_method["publicKeyJwk"]
            if jwk.get("crv") != "secp256k1":
                raise ValueError("Invalid curve for EcdsaSecp256k1VerificationKey2019")
            return _extract_ec_public_key_from_jwk(jwk)
        if "publicKeyMultibase" in verification_method:
            return _extract_secp256k1_public_key_from_multibase(
                verification_method["publicKeyMultibase"]
            )

    elif method_type == "EcdsaSecp256r1VerificationKey2019":
        if "publicKeyJwk" in verification_method:
            jwk = verification_method["publicKeyJwk"]
            if jwk.get("crv") != "P-256":
                raise ValueError("Invalid curve for EcdsaSecp256r1VerificationKey2019")
            return _extract_ec_public_key_from_jwk(jwk)

    elif method_type in [
        "Ed25519VerificationKey2020",
        "Ed25519VerificationKey2018",
        "Multikey",
    ]:
        if "publicKeyJwk" in verification_method:
            jwk = verification_method["publicKeyJwk"]
            if jwk.get("kty") != "OKP" or jwk.get("crv") != "Ed25519":
                raise ValueError(f"Invalid JWK parameters for {method_type}")
            key_bytes = base64.urlsafe_b64decode(
                jwk["x"] + "=" * (-len(jwk["x"]) % 4)
            )
            return ed25519.Ed25519PublicKey.from_public_bytes(key_bytes)
        if "publicKeyBase58" in verification_method:
            return _extract_ed25519_public_key_from_base58(
                verification_method["publicKeyBase58"]
            )
        if "publicKeyMultibase" in verification_method:
            return _extract_ed25519_public_key_from_multibase(
                verification_method["publicKeyMultibase"]
            )

    elif method_type == "JsonWebKey2020":
        if "publicKeyJwk" in verification_method:
            return _extract_ec_public_key_from_jwk(verification_method["publicKeyJwk"])

    raise ValueError(
        f"Unsupported verification method type or missing required key format: {method_type}"
    )


def _find_verification_method(
    did_document: dict, verification_method_id: str
) -> Optional[dict]:
    """在 DID 文档中查找 verificationMethod。

    依次搜索 verificationMethod、authentication、assertionMethod 数组。
    """
    for method in did_document.get("verificationMethod", []):
        if method.get("id") == verification_method_id:
            return method

    for auth in did_document.get("authentication", []):
        if isinstance(auth, str):
            if auth == verification_method_id:
                for method in did_document.get("verificationMethod", []):
                    if method.get("id") == verification_method_id:
                        return method
        elif isinstance(auth, dict) and auth.get("id") == verification_method_id:
            return auth

    for assertion in did_document.get("assertionMethod", []):
        if isinstance(assertion, str):
            if assertion == verification_method_id:
                for method in did_document.get("verificationMethod", []):
                    if method.get("id") == verification_method_id:
                        return method
        elif isinstance(assertion, dict) and assertion.get("id") == verification_method_id:
            return assertion

    return None


def build_did_resolution_url(
    did: str, base_url_override: Optional[str] = None
) -> str:
    """构建 DID 文档的 HTTPS 解析 URL。"""
    parts = did.split(":")
    if len(parts) < 3 or parts[0] != "did":
        raise ValueError("Invalid DID format")

    method = parts[1]
    if method not in {"wba", "web"}:
        raise ValueError(f"Unsupported DID method: {method}")

    domain = urllib.parse.unquote(parts[2])
    path_segments = parts[3:]
    base_url = (base_url_override or f"https://{domain}").rstrip("/")
    if path_segments:
        encoded_path = "/".join(
            urllib.parse.unquote(seg) for seg in path_segments
        )
        return f"{base_url}/{encoded_path}/did.json"
    return f"{base_url}/.well-known/did.json"


# --- DIDResolver 主类 ---


class DIDResolver:
    """带 TTL 缓存和重试的 DID 文档解析器。"""

    def __init__(
        self,
        agent_did: str,
        key_store: KeyStore,
        ttl_seconds: float = 300.0,
        max_retries: int = 2,
        retry_delay: float = 1.0,
        request_timeout: float = 10.0,
    ):
        self._agent_did = agent_did
        self._key_store = key_store
        self._ttl = ttl_seconds
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._request_timeout = request_timeout
        self._cache: dict[str, _CacheEntry] = {}

    async def resolve_public_key(
        self, did: str, key_fragment: str = "key-1"
    ) -> object | None:
        """解析 DID → 公钥（向后兼容接口）。"""
        result = await self.resolve_full(did, key_fragment)
        return result.public_key

    async def resolve_did_document(self, did: str) -> dict | None:
        """解析 DID 文档，带 TTL 缓存和指数退避重试。"""
        # 本地 agent 快捷路径
        if did == self._agent_did:
            return None

        # 缓存命中
        entry = self._cache.get(did)
        if entry and (time.monotonic() - entry.resolved_at < self._ttl):
            return entry.did_document

        # 网络解析 + 重试
        url = build_did_resolution_url(did)
        timeout = aiohttp.ClientTimeout(total=self._request_timeout)
        headers = {"Accept": "application/json"}

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        url, headers=headers, ssl=True
                    ) as response:
                        response.raise_for_status()
                        did_document = await response.json()

                if did_document.get("id") != did:
                    raise ValueError(
                        f"DID document ID mismatch. "
                        f"Expected: {did}, got: {did_document.get('id')}"
                    )

                self._cache[did] = _CacheEntry(
                    did_document=did_document,
                    resolved_at=time.monotonic(),
                )
                return did_document

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                if attempt < self._max_retries:
                    delay = self._retry_delay * (2 ** attempt)
                    logger.warning(
                        "DID resolution attempt %d/%d failed for %s, "
                        "retrying in %.1fs: %s",
                        attempt + 1,
                        self._max_retries + 1,
                        did,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)
            except ValueError:
                raise

        logger.error(
            "DID resolution failed after %d attempts for %s: %s",
            self._max_retries + 1,
            did,
            last_error,
        )
        return None

    def extract_node_type(self, did_doc: dict) -> str | None:
        """从 DID 文档 service 数组提取 ATTPNodeType。"""
        for svc in did_doc.get("service", []):
            if svc.get("type") == ATTP_NODE_TYPE_SERVICE:
                endpoint = svc.get("serviceEndpoint", "")
                # endpoint 格式: "attp:type:agent"
                if endpoint.startswith("attp:type:"):
                    node_type = endpoint[len("attp:type:"):]
                    if node_type in VALID_NODE_TYPES:
                        return node_type
                return None
        return None

    async def resolve_full(
        self, did: str, key_fragment: str = "key-1"
    ) -> DIDResolutionResult:
        """一次调用获取 public_key + node_type + did_document。"""
        # 本地 agent 快捷路径
        if did == self._agent_did:
            public_key = self._key_store.get(did)
            return DIDResolutionResult(
                public_key=public_key,
                node_type="agent",
                did_document=None,
                from_cache=True,
            )

        # 尝试缓存
        entry = self._cache.get(did)
        from_cache = False
        if entry and (time.monotonic() - entry.resolved_at < self._ttl):
            did_doc = entry.did_document
            from_cache = True
        else:
            did_doc = await self.resolve_did_document(did)

        if did_doc is None:
            return DIDResolutionResult(
                public_key=None,
                node_type=None,
                did_document=None,
                from_cache=False,
            )

        # 提取公钥
        key_id = f"{did}#{key_fragment}"
        method = _find_verification_method(did_doc, key_id)
        public_key = None
        if method:
            try:
                public_key = _extract_public_key(method)
            except ValueError as exc:
                logger.warning("Failed to extract public key for %s: %s", did, exc)

        # 提取节点类型
        node_type = self.extract_node_type(did_doc)

        return DIDResolutionResult(
            public_key=public_key,
            node_type=node_type,
            did_document=did_doc,
            from_cache=from_cache,
        )

    def invalidate(self, did: str) -> None:
        """强制失效指定 DID 的缓存。"""
        self._cache.pop(did, None)
