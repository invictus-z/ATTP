"""Protocol Node 独立配置模型与加载器。"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from attp.app.logging import get_logger

logger = get_logger("ProtocolNodeConfig")


class PNBase(BaseModel):
    """Protocol Node 配置基类，支持 camelCase 和 snake_case。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PNWebConfig(PNBase):
    """网络配置（单端口）。"""

    host: str = "0.0.0.0"
    port: int = 9000


class StorageConfig(PNBase):
    """存储配置。"""

    data_dir: str = "~/.attp/protocol_node"
    db_path: str = "attp.db"


class AnalysisConfig(PNBase):
    """语义意图追踪（LLM）配置 — 十字锁定（Cross-Lock）架构。"""

    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    report_batch_size: int = 10

    # Cross-Lock 横向分析配置
    horizontal_enabled: bool = True               # 横向分析开关（依赖 enabled=True）
    horizontal_threshold: int = 5                 # 累积多少次纵向分析后触发横向


class ProtocolNodeConfigFile(PNBase):
    """Protocol Node 配置文件模型。

    对应 JSON 结构：
    {
        "web": { "host": ..., "port": ... },
        "storage": { "dataDir": ..., "dbPath": ... },
        "analysis": { "enabled": ..., ... }
    }
    """

    web: PNWebConfig = Field(default_factory=PNWebConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
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

    def get_db_path(self) -> str:
        """返回拼接后的数据库完整路径。"""
        return str(Path(self.storage.data_dir).expanduser() / self.storage.db_path)