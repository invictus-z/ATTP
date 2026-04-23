"""溯源模块：genesis 标识哈希与链管理。"""

from .hashing import calculate_genesis_hash, calculate_hop_hash
from .chain import ChainManager

__all__ = ["calculate_genesis_hash", "calculate_hop_hash", "ChainManager"]
