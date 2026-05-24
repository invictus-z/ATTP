"""签名与验签引擎。"""

import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec, ed25519, utils as asym_utils
from cryptography.exceptions import InvalidSignature

from attp.app.logging import get_logger

logger = get_logger("Tracing")


def _compact_to_der(sig_bytes: bytes) -> bytes:
    """将 ECDSA compact 签名 (r||s) 转换为 DER 格式。

    JS 端 Web Crypto API / @noble/secp256k1 输出 compact (raw r||s) 格式，
    Python cryptography 库期望 DER 格式。
    """
    half = len(sig_bytes) // 2
    r = int.from_bytes(sig_bytes[:half], "big")
    s = int.from_bytes(sig_bytes[half:], "big")
    return asym_utils.encode_dss_signature(r, s)


def _ec_key_byte_size(key) -> int:
    """返回 EC 密钥曲线对应的字节长度（用于判断 compact 签名长度）。"""
    return (key.key_size + 7) // 8


def sign_hash(entry_hash: str, private_key) -> str:
    """使用私钥对 entry_hash 签名，返回 Base64 编码的签名字符串。"""
    if isinstance(private_key, rsa.RSAPrivateKey):
        signature = private_key.sign(
            entry_hash.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
    elif isinstance(private_key, ec.EllipticCurvePrivateKey):
        signature = private_key.sign(
            entry_hash.encode("utf-8"),
            ec.ECDSA(hashes.SHA256()),
        )
    elif isinstance(private_key, ed25519.Ed25519PrivateKey):
        signature = private_key.sign(entry_hash.encode("utf-8"))
    else:
        return ""
    return base64.b64encode(signature).decode("utf-8")


def verify_signature(entry_hash: str, signature_b64: str, public_key) -> bool:
    """用公钥验证 entry_hash 的签名。

    Args:
        entry_hash: SHA-256 hex 字符串（与 sign_hash 输入一致）
        signature_b64: Base64 编码的签名
        public_key: rsa.RSAPublicKey 或 ec.EllipticCurvePublicKey

    Returns:
        True 签名合法，False 验证失败
    """
    try:
        sig_bytes = base64.b64decode(signature_b64)
        data = entry_hash.encode("utf-8")

        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(
                sig_bytes, data,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH,
                ),
                hashes.SHA256(),
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            # 先尝试 DER 格式（Python cryptography 原生输出）
            try:
                public_key.verify(sig_bytes, data, ec.ECDSA(hashes.SHA256()))
                return True
            except InvalidSignature:
                pass
            # DER 失败，尝试 compact (r||s) 格式（JS Web Crypto API / @noble/secp256k1 输出）
            expected_compact_len = _ec_key_byte_size(public_key) * 2
            if len(sig_bytes) == expected_compact_len:
                der_sig = _compact_to_der(sig_bytes)
                public_key.verify(der_sig, data, ec.ECDSA(hashes.SHA256()))
            else:
                raise InvalidSignature("Signature length mismatch")
        elif isinstance(public_key, ed25519.Ed25519PublicKey):
            public_key.verify(sig_bytes, data)
        else:
            logger.error(f"Unsupported key type: {type(public_key)}")
            return False
        return True
    except InvalidSignature:
        return False
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False
