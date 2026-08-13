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
    """语义意图追踪（LLM）配置 — 逐跳有状态改版（三元组 + F 累加 + 横轴确认）。

    taint_score 取 [0,10]（0.5 步进，5 档 severity）。详见
    ``core/analysis/base_models.py`` 的评分常量与 ``core/analysis/`` 的实现。
    """

    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"

    # 横轴开关（依赖 enabled=True）
    horizontal_enabled: bool = True

    # ── 评分聚合 ──
    dimensions: int = 4                  # 正交维度数（默认 4，见 base_models.DIMENSION_NAMES）
    aggregation: str = "max"             # 维度聚合："max"(默认) / "sum" / 数值 p 的 L^p 范数

    # ── 阈值（R_S 已标定：三次方累计 cube@R_S=200，见 §9 benchmark rq_rs_trigger_f1）──
    r_t: float = 7.5                     # 单点阈值：s_i > R_T 立即告警（critical 下沿）
    rho: float = 8.0                     # 横轴高危兜底：会话内任一跳 s_j ≥ ρ 无条件纳入确认
    rho_k: float = 8.0                   # 单维 critical：d_k ≥ ρ_k（max 聚合下自动成立）
    r_s: float = 200.0                   # 累积阈值：F_d = Σ s_i³ > R_S 触发横轴确认（三次方和；实验最佳 cube@R_S=200）
    alpha: int = 10                      # 横轴确认上限：候选会话 > α 时按 W(σ) 取 α 个；≤ α 取全量

    # ── 异步 ──
    concurrency: int = 8                 # 同时处理的 hop 数（全局并发上限；每个 worker 处理一跳前获取此信号量）
    queue_maxsize: int = 1000            # 单会话有界队列容量（真背压：满则该跳留 DB，由 catch-up 扫描补打，不丢数据）


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