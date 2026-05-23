"""ToolNodeMixin — 三种 SDK 工具节点的共用回传逻辑。

提取 ATTPToolNode / MCPToATTPAdapter / MCPProxyToolNode 的共同代码：
- NodeMessage(A2T) 解析
- BackMessage 构建与发送
- RecordedHop_T2A 构建 + 签名
- _handle_tool_request 模板方法
- _handle_record
- FastAPI 路由注册
- ad.json 生成
- start / stop 生命周期

子类只需实现 ``_execute_tool(tool_name, arguments) -> (result_str, status_code)``。
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from attp.core.authentication.keys import KeyStore, load_private_key
from attp.core.authentication.signatures import sign_hash
from attp.core.message.event import NodeMessage, RecordedHop
from attp.core.message.back_sender import send_back_message, BackPropagationError
from attp.core.provenance.chain import ChainManager
from attp.core.storage import SqliteStore
from attp.core.pn_tracer import ProtocolTracer

logger = logging.getLogger("attp.sdk.tools.mixin")


class ToolNodeMixin(abc.ABC):
    """工具节点共用逻辑 Mixin。

    要求宿主类提供以下属性：
        did: str
        name: str
        description: str
        host: str
        port: int
        private_key_path: Path
        attp_prefix: str
        _key_store: KeyStore
        _chain: ChainManager
        _storage: SqliteStore
        _tracer: ProtocolTracer
        _ad_output_path: Path
        _app: FastAPI
        _uvicorn_server: uvicorn.Server | None
        _serve_task: asyncio.Task | None

    以及抽象方法：
        _execute_tool(tool_name, arguments) -> tuple[str, int]
        _build_ad() -> ToolAd
    """

    # ------------------------------------------------------------------
    # 抽象方法 — 子类必须实现
    # ------------------------------------------------------------------

    @abc.abstractmethod
    async def _execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, int]:
        """执行工具并返回 (result_str, http_status_code)。

        - 200 表示成功，result_str 为工具返回内容
        - 4xx/5xx 表示失败，result_str 为错误描述
        """
        ...

    @abc.abstractmethod
    def _build_ad(self):
        """子类实现：构建 ToolAd 对象。"""
        ...

    # ------------------------------------------------------------------
    # 共用初始化辅助 — 在子类 __init__ 末尾调用
    # ------------------------------------------------------------------

    def _init_common(
        self,
        did: str,
        name: str,
        description: str,
        host: str,
        port: int,
        private_key_path: str,
        attp_prefix: str,
        db_path: str,
        ad_output_path: str | None,
        app_title: str,
    ) -> None:
        """设置共用属性 + FastAPI 路由。子类 __init__ 末尾调用。"""
        self.did = did
        self.name = name
        self.description = description
        self.host = host
        self.port = port
        self.private_key_path = Path(private_key_path).expanduser()
        self.attp_prefix = attp_prefix

        self._key_store = KeyStore()
        self._chain = ChainManager(self._key_store)
        self._storage = SqliteStore(db_path)
        self._tracer = ProtocolTracer(db_path)

        self._app = FastAPI(title=app_title)
        self._setup_routes()

        self._uvicorn_server = None
        self._serve_task = None
        self._ad_output_path = Path(ad_output_path) if ad_output_path else Path("ad.json")

    # ------------------------------------------------------------------
    # FastAPI 路由注册
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        """设置 FastAPI 路由（tool_request / record / ad.json / health）。"""

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

    # ------------------------------------------------------------------
    # NodeMessage 解析
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_node_message(body: dict) -> tuple[
        NodeMessage | None, RecordedHop | None, str, str, str
    ]:
        """从 request body 解析 node_message 字段。

        Returns:
            (NodeMessage, RecordedHop, session_id, protocol_node_address, nonce)
            解析失败时前两项为 None。
        """
        data = body.get("node_message")
        if not data:
            return None, None, "", "", ""
        try:
            nm = NodeMessage.from_dict(data)
            rh = nm.recorded_hop
            return nm, rh, rh.session_id, nm.protocol_url, nm.nonce
        except Exception as e:
            logger.warning("Failed to parse NodeMessage from request: %s", e)
            return None, None, "", "", ""

    # ------------------------------------------------------------------
    # _handle_tool_request — 模板方法
    # ------------------------------------------------------------------

    async def _handle_tool_request(self, body: dict) -> JSONResponse:
        """处理 tool_request 消息（完整 2 次回传模板）。

        === 第一跳 A2T 确认 ===
        1. 解析 NodeMessage(A2T)
        2. 执行工具（子类 _execute_tool）
        3. BackMessage #2 (Phase 1, Tool 确认 A2T) → Protocol Node（严格门控）

        === 第二跳 T2A (Tool → Agent) ===
        4. 构建 RecordedHop_T2A（Tool 签名）
        5. BackMessage #3 (Phase 2, Tool 报告 T2A) → Protocol Node（严格门控）
        6. 确认后返回 tool_response（含 NodeMessage(T2A)）
        """
        sender_did = body.get("sender_did", "")
        tool_name = body.get("tool_name", "")
        arguments_str = body.get("arguments", "{}")

        # 1. 解析 NodeMessage(A2T)
        _, recorded_hop_a2t, session_id, protocol_url, nonce = \
            self._parse_node_message(body)

        # 2. 解析参数
        try:
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str
        except json.JSONDecodeError:
            return JSONResponse(
                {"error": f"Invalid arguments JSON: {arguments_str}"},
                status_code=400,
            )

        # 3. 执行工具（子类实现）
        result_str, status_code = await self._execute_tool(tool_name, arguments)
        if status_code != 200:
            return JSONResponse({"error": result_str}, status_code=status_code)

        # 4. 加载私钥
        private_key = None
        try:
            private_key = load_private_key(str(self.private_key_path))
        except Exception as e:
            logger.error("Failed to load private key: %s", e)

        # === 第一跳 A2T: BackMessage #2 (Phase 1, Tool 确认) → Protocol Node ===
        if protocol_url and recorded_hop_a2t and private_key:
            try:
                await send_back_message(
                    protocol_url=protocol_url,
                    node_did=self.did,
                    nonce=nonce,
                    recorded_hop=recorded_hop_a2t,
                    private_key=private_key,
                )
            except BackPropagationError as e:
                return JSONResponse({"error": f"BackMessage #2 failed: {e}"}, status_code=502)

        # === 第二跳 T2A: 构建 RecordedHop_T2A ===
        t2a_nonce = f"{nonce}_t2a" if nonce else f"{tool_name}_{time.time()}"
        recorded_hop_t2a = RecordedHop(
            session_id=session_id,
            sender_did=self.did,
            target_did=sender_did,
            content=f"tool_response({tool_name}): {result_str[:200]}",
            timestamp=time.time(),
            hop_count=list(recorded_hop_a2t.hop_count) if recorded_hop_a2t else [0, 0],
        )

        if private_key:
            try:
                recorded_hop_t2a.sig_content = sign_hash(
                    recorded_hop_t2a.content_hash(), private_key,
                )
            except Exception as e:
                logger.error("Failed to sign RecordedHop_T2A: %s", e)

        node_message_t2a = NodeMessage(
            protocol_url=protocol_url,
            nonce=t2a_nonce,
            recorded_hop=recorded_hop_t2a,
        )

        # === 第二跳 T2A: BackMessage #3 (Phase 2, Tool 报告) → Protocol Node ===
        if protocol_url and private_key:
            try:
                await send_back_message(
                    protocol_url=protocol_url,
                    node_did=self.did,
                    nonce=t2a_nonce,
                    recorded_hop=recorded_hop_t2a,
                    private_key=private_key,
                )
            except BackPropagationError as e:
                return JSONResponse({"error": f"BackMessage #3 failed: {e}"}, status_code=502)

        # 返回 tool_response（含 NodeMessage(T2A)）
        return JSONResponse({
            "result": result_str,
            "tool_name": tool_name,
            "tool_did": self.did,
            "message_type": "tool_response",
            "node_message": node_message_t2a.to_dict(),
        })

    # ------------------------------------------------------------------
    # _handle_record
    # ------------------------------------------------------------------

    async def _handle_record(self, body: dict) -> JSONResponse:
        """处理 record 消息 — 保存远端 NodeMessage。"""
        metadata = body.get("metadata", {})
        node_msg_data = metadata.get("NodeMessage")
        if node_msg_data:
            try:
                NodeMessage.from_dict(node_msg_data)
                logger.info("Record saved for node=%s", node_msg_data.get("node_did", "unknown"))
            except Exception as e:
                logger.warning("Failed to save NodeMessage: %s", e)
        return JSONResponse({"status": "Record saved"})

    # ------------------------------------------------------------------
    # ad.json
    # ------------------------------------------------------------------

    def generate_ad(self, output_path: str | None = None):
        """生成并保存 ad.json 文件。"""
        from attp.sdk.tools.tool_ad import ToolAd  # avoid circular

        ad = self._build_ad()
        path = Path(output_path) if output_path else self._ad_output_path
        ad.save_to_file(path)
        logger.info("Generated ad.json at %s", path)
        return ad

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动 ATTP 工具节点服务。"""
        self.generate_ad()

        config = uvicorn.Config(
            self._app, host=self.host, port=self.port, log_level="info",
        )
        self._uvicorn_server = uvicorn.Server(config)

        async def _run():
            await self._uvicorn_server.serve()

        self._serve_task = asyncio.create_task(_run())
        logger.info(
            "%s '%s' started at %s:%d (DID: %s)",
            type(self).__name__, self.name, self.host, self.port, self.did,
        )

    async def stop(self) -> None:
        """停止 ATTP 工具节点服务。"""
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._serve_task.cancel()
                try:
                    await self._serve_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
        logger.info("%s '%s' stopped", type(self).__name__, self.name)