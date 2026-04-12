"""签名与验签引擎。"""

import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ec
from cryptography.exceptions import InvalidSignature

from attp_channel.logging import get_logger

logger = get_logger("Tracing")


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
            public_key.verify(sig_bytes, data, ec.ECDSA(hashes.SHA256()))
        else:
            logger.error(f"Unsupported key type: {type(public_key)}")
            return False
        return True
    except InvalidSignature:
        return False
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False
