"""溯源与哈希链相关模块。"""

from .hashing import calculate_entry_hash
from .chain import ChainManager

__all__=["calculate_entry_hash", "ChainManager"]
