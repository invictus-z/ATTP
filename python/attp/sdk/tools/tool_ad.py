"""Tool AD — ATTP 工具节点的服务描述文件（ad.json）生成工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ToolAd:
    """ATTP 工具节点描述文件构建器。"""

    def __init__(
        self,
        did: str,
        name: str,
        description: str = "",
        attp_endpoint: str = "",
        mcp_tools: list[dict[str, Any]] | None = None,
        public_key_endpoint: str = "",
        version: str = "0.1.0",
    ):
        self.did = did
        self.name = name
        self.description = description
        self.attp_endpoint = attp_endpoint
        self.mcp_tools = mcp_tools or []
        self.public_key_endpoint = public_key_endpoint
        self.version = version
        self.type = "attp-tool-node"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "version": self.version,
            "identifier": self.did,
            "name": self.name,
            "description": self.description,
            "attp_endpoint": self.attp_endpoint,
            "public_key_endpoint": self.public_key_endpoint,
            "mcp_tools": self.mcp_tools,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save_to_file(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolAd:
        return cls(
            did=data.get("identifier", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            attp_endpoint=data.get("attp_endpoint", ""),
            mcp_tools=data.get("mcp_tools", []),
            public_key_endpoint=data.get("public_key_endpoint", ""),
            version=data.get("version", "0.1.0"),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> ToolAd:
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)