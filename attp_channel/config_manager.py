"""Configuration manager for ANP config — read/write ~/.nanobot/anp/anp_config.json."""

from __future__ import annotations

import json
import copy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


# ---------------------------------------------------------------------------
# ANP config Pydantic models (mirrors anp_config.json structure)
# ---------------------------------------------------------------------------

class ANPBase(BaseModel):
    """Accept both camelCase and snake_case keys."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ANPClientConfig(ANPBase):
    """ANP client configuration (anp_config.json → anp_client)."""

    did_doc_path: str = Field(default="", alias="didDocPath")
    did_key_path: str = Field(default="", alias="didKeyPath")
    node_ads: list[str] = Field(default_factory=list)


class ANPServerConfig(ANPBase):
    """ANP server configuration (anp_config.json → anp_server)."""

    name: str = ""
    prefix: str = "/agent"
    description: str = ""
    server_port: int = Field(default=8000, alias="serverPort")
    private_key_path: str = ""
    public_key_path: str = ""


class ANPConfigFile(ANPBase):
    """Root model for ~/.nanobot/anp/anp_config.json."""

    did: str = ""
    anp_client: ANPClientConfig = Field(default_factory=ANPClientConfig)
    anp_server: ANPServerConfig = Field(default_factory=ANPServerConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep-merge *override* into *base*, returning a new dict."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Manager for ANP config file."""

    def __init__(self, anp_config_path: str | Path):
        self._anp_path = Path(anp_config_path).expanduser()
        self.anp_config: ANPConfigFile = ANPConfigFile()

    # ---- Read ----

    def load(self) -> None:
        """Load ANP config from disk."""
        if self._anp_path.exists():
            try:
                with open(self._anp_path, encoding="utf-8") as f:
                    data = json.load(f)
                self.anp_config = ANPConfigFile.model_validate(data)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"Warning: Failed to load ANP config from {self._anp_path}: {e}")

    # ---- Write ----

    def update(self, partial: dict[str, Any]) -> ANPConfigFile:
        """Partially update ANP config, validate, save to file, and reload.

        Args:
            partial: A (potentially nested) dict matching anp_config.json structure.

        Returns:
            The updated ANPConfigFile object.
        """
        if self._anp_path.exists():
            with open(self._anp_path, encoding="utf-8") as f:
                current_data = json.load(f)
        else:
            current_data = {}

        merged = _deep_merge(current_data, partial)
        self.anp_config = ANPConfigFile.model_validate(merged)
        self._anp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._anp_path, "w", encoding="utf-8") as f:
            json.dump(self.anp_config.model_dump(by_alias=True), f, indent=4, ensure_ascii=False)
        return self.anp_config