"""端口一：数据处理端 — 接收 record 消息、验证、储存、触发分析。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("DataPort")

if TYPE_CHECKING:
    from attp.core.tracer import MessageTracer
    from attp.core.sessions.protocol_node import ProtocolSessionManager


class DataPort:
    """Protocol Node 端口一：record 接收 + 验证 + 储存。"""

    def __init__(
        self,
        tracer: MessageTracer,
        session_manager: ProtocolSessionManager,
        agent_did: str,
        host: str,
        port: int,
        did_resolver=None,
        behavior_controller=None,
    ):
        self._tracer = tracer
        self._session_manager = session_manager
        self._agent_did = agent_did
        self.host = host
        self.port = port
        self._did_resolver = did_resolver
        self._behavior_controller = behavior_controller
        self._app = FastAPI(title="ATTP Protocol Node — Data Port")
        self._orchestrator = None
        self._uvicorn_server = None
        self._serve_task = None

        # Closure captures for endpoint handlers
        tracer_ref = self._tracer
        session_mgr = self._session_manager
        agent_did = self._agent_did
        did_resolver_ref = self._did_resolver
        behavior_controller_ref = self._behavior_controller
        _orch_holder = [None]  # mutable list for late-binding

        @self._app.post("/record")
        async def receive_record(request: Request) -> JSONResponse:
            """接收并处理 record 消息。"""
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

            metadata = body.get("metadata") or {}
            session_id = metadata.get("Session_ID")
            pna = metadata.get("Protocol_Node_Address")

            # === Nonce 验证管道 ===
            if did_resolver_ref:
                from attp.protocol_node.middleware import intercept_record

                result = await intercept_record(
                    body, did_resolver_ref, tracer_ref,
                    chain_manager=tracer_ref._chain,
                    session_manager=session_mgr,
                    agent_did=agent_did,
                )

                if result.status == "error":
                    ERROR_MAP = {
                        "missing_record_log": (400, "Missing Record_Log"),
                        "hop_validation": (400, "Hop validation failed"),
                        "did_resolution_failed": (404, "DID resolution failed"),
                        "missing_type_field": (400, "Missing ATTPNodeType"),
                        "invalid_type": (400, "Invalid ATTP node type"),
                        "missing_nonce": (400, "Missing nonce"),
                        "missing_identity_signature": (400, "Missing Identity_Signature"),
                        "identity_signature_invalid": (403, "Identity signature invalid"),
                        "sender_mismatch_not_self": (403, "Sender mismatch"),
                        "receiver_mismatch": (403, "Receiver mismatch"),
                        "back_propagation": (403, "Back-propagation verification failed"),
                        "invalid_type_combination": (400, "Invalid type combination"),
                        "hop_count_violation_a2a": (400, "Hop count violation (A2A must +1)"),
                        "hop_count_violation_non_a2a": (400, "Hop count violation (non-A2A must stay)"),
                        "hop_zero_must_be_u2a": (400, "hop_count=0 must be U2A (user intent)"),
                    }
                    error_key = result.error.split(":")[0] if result.error else ""
                    code, msg = ERROR_MAP.get(
                        error_key, (500, result.error or "Unknown error")
                    )
                    return JSONResponse({"error": msg}, status_code=code)

                if result.status == "stored":
                    # Branch A: 仅暂存，不触发存储和分析
                    return JSONResponse({"status": "Pending record stored"})

                if result.status == "verified":
                    # Branch B: 全部验证通过，存储行为记录
                    behavior_type = result.behavior_type
                    stored = result.stored_msg

                    await tracer_ref.save_behavior_entry(
                        session_id=session_id,
                        protocol_node_address=pna,
                        node_did=stored.sender_did,
                        hop_count=stored.hop.get("Hop_Count", 0),
                        field_type=behavior_type,
                        content=stored.hop.get("Content", ""),
                        target=stored.hop.get("target_did", ""),
                        timestamp=stored.hop.get("Timestamp", 0),
                    )
                    logger.info(
                        "BehaviorEntry saved: sender={}, receiver={}, type={}",
                        stored.sender_did, result.sender_did, behavior_type,
                    )

                    if behavior_controller_ref:
                        await behavior_controller_ref.handle(
                            behavior_type, body, result,
                        )

                    # U2A (hop_count=0) 作为用户意图入口，通知 orchestrator 提取 intent
                    _orch = _orch_holder[0]
                    if behavior_type == "U2A" and _orch and session_id:
                        content = stored.hop.get("Content", "")
                        await _orch.on_field_U2A_recorded(session_id, content)

                    # 触发分析
                    if _orch and session_id:
                        await _orch.on_record_received(session_id)

                    return JSONResponse({"status": "Record verified and saved"})
            # === 结束 ===

            return JSONResponse({"status": "No log in record metadata"})

        # Store mutable reference for set_orchestrator
        self._orch_holder = _orch_holder

    def set_orchestrator(self, orchestrator) -> None:
        """注入 AnalysisOrchestrator。"""
        self._orchestrator = orchestrator
        self._orch_holder[0] = orchestrator

    async def start(self) -> None:
        """启动 Data Port uvicorn 服务。"""
        cfg = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
            log_config=UVICORN_SILENT_LOG_CONFIG,
        )
        self._uvicorn_server = uvicorn.Server(cfg)
        self._serve_task = asyncio.create_task(self._uvicorn_server.serve())
        logger.info("started at {}:{}", self.host, self.port)

    async def stop(self) -> None:
        """停止 Data Port。"""
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
