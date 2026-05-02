""" ATTP统一配置管理界面 — read/write ~/.nanobot/attp/attp_config.json."""

from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from attp.app.logging import get_logger
from pydantic.alias_generators import to_camel

logger = get_logger("Config")


# ---------------------------------------------------------------------------
# ATTP config Pydantic models
# ---------------------------------------------------------------------------

class ATTPBase(BaseModel):
    """Accept both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    def changed_fields(self, other: ATTPBase) -> set[str]:
        """Return the set of field names whose values differ from *other*."""
        self_dict = self.model_dump()
        other_dict = other.model_dump()
        return {key for key in self_dict if self_dict[key] != other_dict[key]}


class ATTPClientConfig(ATTPBase):
    """ATTP client configuration (attp_config.json → attp_client)."""

    did_doc_path: str = Field(default="", alias="didDocPath")
    did_key_path: str = Field(default="", alias="didKeyPath")
    node_ads: list[str] = Field(default_factory=list)

class ATTPServerConfig(ATTPBase):
    """ATTP server configuration (attp_config.json → attp_server)."""

    name: str = ""
    prefix: str = "/agent"
    description: str = ""
    server_host: str = "127.0.0.1"
    server_port: int = Field(default=8000, alias="serverPort")
    private_key_path: str = ""
    public_key_path: str = ""

class WebAppConfig(ATTPBase):
    """Web app configuration (attp_config.json → web_app)."""

    host: str = "127.0.0.1"
    port: int = 8001

class ToolConfig(ATTPBase):
    host: str = "127.0.0.1"
    port: int = 8002

class HeartbeatConfig(ATTPBase):
    interval: int = 30
    timeout: int = 90
    max_fail: int = 3

class StorageConfig(ATTPBase):
    """Storage configuration for tracer database."""

    data_dir: str = Field(alias="dataDir")
    db_path: str = Field(default="attp_traces.db", alias="dbPath")

class ATTPConfigFile(ATTPBase):
    """Root model for ~/.nanobot/attp/attp_config.json."""

    did: str = ""
    attp_client: ATTPClientConfig = Field(default_factory=ATTPClientConfig)
    attp_server: ATTPServerConfig = Field(default_factory=ATTPServerConfig)
    web_app: WebAppConfig = Field(default_factory=WebAppConfig)
    tool: ToolConfig = Field(default_factory=ToolConfig)
    heartbeat: HeartbeatConfig = Field(default_factory=HeartbeatConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


def _deep_merge(base: dict, override: dict, list_strategy: str = "extend") -> dict:
    """Deep-merge *override* into *base*, returning a new dict.

    Args:
        base: The base dictionary.
        override: The override dictionary.
        list_strategy: How to handle list values - "extend" (dedup merge)
                       or "replace" (override entirely).
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value, list_strategy)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            if list_strategy == "extend":
                merged = list(result[key])
                for item in value:
                    if item not in merged:
                        merged.append(item)
                result[key] = merged
            else:
                result[key] = copy.deepcopy(value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Manager for ATTP config file."""

    def __init__(self, attp_config_path: str | Path):
        self._attp_path = Path(attp_config_path).expanduser()
        self.attp_config: ATTPConfigFile = ATTPConfigFile()

    # ---- Read ----

    def load(self) -> None:
        """Load ATTP config from disk."""
        if self._attp_path.exists():
            try:
                with open(self._attp_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.attp_config = ATTPConfigFile.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Failed to load ATTP config from {}: {}", self._attp_path, e)

    # ---- Write ----

    def update(self, partial: dict[str, Any]) -> ATTPConfigFile: # 支持部分更新
        """Partially update ATTP config, validate, save to file, and reload.

        Args:
            partial: A (potentially nested) dict matching attp_config.json structure.

        Returns:
            The updated ATTPConfigFile object.
        """
        if self._attp_path.exists():
            with open(self._attp_path, encoding="utf-8") as f:
                current_data = json.load(f)
        else:
            current_data = {}

        merged = _deep_merge(current_data, partial)
        self.attp_config = ATTPConfigFile.model_validate(merged)
        self._attp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._attp_path, "w", encoding="utf-8") as f:
            json.dump(self.attp_config.model_dump(by_alias=True), f, indent=4, ensure_ascii=False)
        return self.attp_config