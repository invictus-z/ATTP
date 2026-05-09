"""Protocol Node 独立启动配置模型与加载器。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from attp.app.config.config import (
    ATTPBase,
    AnalysisConfig,
    ProtocolNodeConfig,
    StorageConfig,
)
from attp.app.logging import get_logger

logger = get_logger("ProtocolNodeConfig")


class ProtocolNodeConfigFile(ATTPBase):
    """独立启动时使用的配置文件模型（~/.nanobot/attp/protocol_node_config.json）。"""

    agent_did: str = ""
    protocol_node: ProtocolNodeConfig = Field(default_factory=ProtocolNodeConfig)
    storage: StorageConfig = Field(default_factory=lambda: StorageConfig(data_dir="~/.nanobot/attp"))
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)

    @classmethod
    def load(cls, path: str | Path) -> ProtocolNodeConfigFile:
        """从 JSON 文件加载配置。文件不存在或无效时返回默认值。"""
        p = Path(path).expanduser()
        if p.exists():
            try:
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                cfg = cls.model_validate(data)
                logger.info("Loaded config from {}", p)
                return cfg
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load config from {}: {}", p, e)
        else:
            logger.info("Config file not found at {}, using defaults", p)
        return cls()

    def save(self, path: str | Path) -> None:
        """保存配置到 JSON 文件。"""
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(by_alias=True), f, indent=4, ensure_ascii=False)
