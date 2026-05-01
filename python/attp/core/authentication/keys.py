"""密钥加载与缓存管理。"""

from pathlib import Path
from cryptography.hazmat.primitives import serialization


def load_private_key(key_path: str):
    """从 PEM 文件加载私钥。"""
    pth = Path(key_path).expanduser().resolve()
    if not pth.exists():
        raise FileNotFoundError(f"Private key not found at {pth}")
    with open(pth, "rb") as key_file:
        return serialization.load_pem_private_key(key_file.read(), password=None)


class KeyStore:
    """管理公钥缓存 (node_did -> public_key) 以及私钥缓存 (path -> private_key)。"""

    def __init__(self) -> None:
        self._cache: dict[str, object] = {}
        self._private_key_cache: dict[str, object] = {}

    def cache_public_key(self, node_did: str, public_key) -> None:
        """注入公钥到缓存。"""
        self._cache[node_did] = public_key

    def get(self, node_did: str):
        """获取缓存的公钥，不存在返回 None。"""
        return self._cache.get(node_did)

    @property
    def cache_dict(self) -> dict:
        """暴露内部字典引用，维持 tracer._pub_key_cache 的兼容性。"""
        return self._cache

    def load_private_key(self, key_path: str):
        """加载私钥并缓存，后续调用相同路径直接返回缓存。

        Args:
            key_path: 私钥 PEM 文件路径。

        Returns:
            加载后的私钥对象。
        """
        resolved = str(Path(key_path).expanduser().resolve())
        if resolved not in self._private_key_cache:
            self._private_key_cache[resolved] = load_private_key(key_path)
        return self._private_key_cache[resolved]
