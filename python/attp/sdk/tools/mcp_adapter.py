"""MCPToATTPAdapter — 将已有 MCP Server 包装为 ATTP 工具节点。

适用场景：已有 MCP Server 实现（FastMCP 实例），直接暴露为 ATTP 工具节点。

使用方式：
    from mcp.server.fastmcp import FastMCP
    from attp.sdk.tools import MCPToATTPAdapter

    my_mcp = FastMCP("my-service")

    @my_mcp.tool()
    async def search(query: str) -> str:
        return "results..."

    adapter = MCPToATTPAdapter(
        did="did:wba:tool.local:search-service",
        name="search-service",
        mcp_server=my_mcp,
        private_key_path="key.pem",
        port=9000,
    )
    await adapter.start()
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from attp.core.authentication.keys import KeyStore
from attp.core.provenance.chain import ChainManager
from attp.core.sessions.node_message import NodeMessage
from attp.core.storage.sqlite_store import SqliteStore
from attp.core.pn_tracer import ProtocolTracer
from attp.sdk.tools.tool_ad import ToolAd

import logging

logger = logging.getLogger("attp.sdk.tools.mcp_adapter")


class MCPToATTPAdapter:
    """将已有 MCP Server (FastMCP) 包装为 ATTP 工具节点。"""

    def __init__(
        self,
        did: str,
        name: str,
        mcp_server: FastMCP,
        private_key_path: str,
        host: str = "0.0.0.0",
        port: int = 9000,
        description: str = "",
        db_path: str = "tool_node_traces.db",
        ad_output_path: str | None = None,
        attp_prefix: str = "/attp",
    ):
        self.did = did
        self.name = name
        self.description = description
        self.host = host
        self.port = port
        self.mcp_server = mcp_server
        self.private_key_path = Path(private_key_path).expanduser()
        self.attp_prefix = attp_prefix

        self._key_store = KeyStore()
        self._chain = ChainManager(self._key_store)
        self._storage = SqliteStore(db_path)
        self._tracer = ProtocolTracer(db_path)

        self._app = FastAPI(title=f"ATTP Tool Node (MCP Adapter): {name}")
        self._setup_routes()

        self._uvicorn_server = None
        self._serve_task = None
        self._ad_output_path = Path(ad_output_path) if ad_output_path else Path("ad.json")

    def _extract_tools_from_mcp(self) -> list[dict[str, Any]]:
        """从 FastMCP 实例提取工具列表。"""
        tools = []
        try:
            tool_manager = getattr(self.mcp_server, '_tool_manager', None)
            if tool_manager:
                for tool_name, tool_obj in tool_manager._tools.items():
                    tools.append({
                        "name": tool_name,
                        "description": getattr(tool_obj, 'description', '') or '',
                        "inputSchema": getattr(tool_obj, 'parameters', {}) or {},
                    })
        except Exception as e:
            logger.warning("Failed to extract tools from FastMCP: %s", e)
        return tools

    def _setup_routes(self) -> None:
        @self._app.post(self.attp_prefix)
        async def handle_attp_request(request: Request) -> JSONResponse:
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

            message_type = body.get("message_type", "")
            if message_type == "tool_request":
                return await self._handle_tool_request(body)
            elif message_type == "record":
                return await self._handle_record(body)
            else:
                return JSONResponse(
                    {"error": f"Unknown message_type: {message_type}"},
                    status_code=400,
                )

        @self._app.get(f"{self.attp_prefix}/ad.json")
        async def get_ad(request: Request) -> JSONResponse:
            return JSONResponse(self._build_ad().to_dict())

        @self._app.get(f"{self.attp_prefix}/health")
        async def health(request: Request) -> JSONResponse:
            return JSONResponse({"status": "ok", "did": self.did})

    async def _handle_tool_request(self, body: dict) -> JSONResponse:
        sender_did = body.get("sender_did", "")
        tool_name = body.get("tool_name", "")
        arguments_str = body.get("arguments", "{}")
        metadata = body.get("metadata", {})
        session_id = metadata.get("Session_ID", "")

        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": f"Invalid arguments JSON: {arguments_str}"},
                status_code=400,
            )

        try:
            result = await self.mcp_server.call_tool(tool_name, arguments)
            if isinstance(result, list):
                result_str = "\n".join(
                    getattr(item, 'text', str(item)) for item in result
                )
            else:
                result_str = str(result)
        except Exception as e:
            logger.exception("MCP tool execution failed: %s", tool_name)
            return JSONResponse(
                {"error": f"Tool execution failed: {str(e)}"},
                status_code=500,
            )

        origin_did = metadata.get("Origin_DID", sender_did)
        hop_count = metadata.get("Hop", {}).get("Hop_Count", 0) + 1

        if session_id:
            try:
                self._tracer.save_behavior_entry(
                    session_id=session_id,
                    origin_did=origin_did,
                    node_did=self.did,
                    hop_count=hop_count,
                    field_type="T2A",
                    content=f"tool_response({tool_name}): {result_str[:500]}",
                    target=sender_did,
                    timestamp=time.time(),
                )
            except Exception as e:
                logger.warning("Failed to save T2A behavior: %s", e)

        response_metadata = dict(metadata)
        try:
            response_metadata = self._tracer.append_hop(
                metadata=response_metadata,
                content=f"tool_response:{tool_name}",
                node_did=self.did,
                target_did=sender_did,
                private_key_path=str(self.private_key_path),
            )
        except Exception as e:
            logger.error("Failed to append hop: %s", e)

        return JSONResponse({
            "result": result_str,
            "tool_name": tool_name,
            "tool_did": self.did,
            "message_type": "tool_response",
            "metadata": response_metadata,
        })

    async def _handle_record(self, body: dict) -> JSONResponse:
        metadata = body.get("metadata", {})
        node_msg_data = metadata.get("NodeMessage")
        if node_msg_data:
            try:
                node_message = NodeMessage.from_dict(node_msg_data)
                self._tracer.save_node_message(node_message)
            except Exception as e:
                logger.warning("Failed to save NodeMessage: %s", e)
        return JSONResponse({"status": "Record saved"})

    def _build_ad(self) -> ToolAd:
        attp_endpoint = f"http://{self.host}:{self.port}{self.attp_prefix}"
        if self.host == "0.0.0.0":
            attp_endpoint = f"http://localhost:{self.port}{self.attp_prefix}"
        return ToolAd(
            did=self.did,
            name=self.name,
            description=self.description,
            attp_endpoint=attp_endpoint,
            mcp_tools=self._extract_tools_from_mcp(),
        )

    def generate_ad(self, output_path: str | None = None) -> ToolAd:
        ad = self._build_ad()
        path = Path(output_path) if output_path else self._ad_output_path
        ad.save_to_file(path)
        logger.info("Generated ad.json at %s", path)
        return ad

    async def start(self) -> None:
        self.generate_ad()
        config = uvicorn.Config(
            self._app, host=self.host, port=self.port, log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(config)

        async def _run():
            await self._uvicorn_server.serve()

        self._serve_task = asyncio.create_task(_run())
        logger.info(
            "MCPToATTPAdapter '%s' started at %s:%d (DID: %s)",
            self.name, self.host, self.port, self.did,
        )

    async def stop(self) -> None:
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except asyncio.CancelledError:
                    pass
        logger.info("MCPToATTPAdapter '%s' stopped", self.name)