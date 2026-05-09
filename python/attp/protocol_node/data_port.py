"""端口一：数据处理端 — 接收 record 消息、储存、验证、触发分析。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from attp.app.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("DataPort")

if TYPE_CHECKING:
    from attp.core.tracer import MessageTracer
    from attp.core.sessions import SessionManager


class DataPort:
    """Protocol Node 端口一：record 接收 + 验证 + 储存。"""

    def __init__(
        self,
        tracer: MessageTracer,
        session_manager: SessionManager,
        agent_did: str,
        host: str,
        port: int,
    ):
        self._tracer = tracer
        self._session_manager = session_manager
        self._agent_did = agent_did
        self.host = host
        self.port = port
        self._app = FastAPI(title="ATTP Protocol Node — Data Port")
        self._orchestrator = None
        self._uvicorn_server = None
        self._serve_task = None

        # Closure captures for endpoint handlers
        tracer_ref = self._tracer
        session_mgr = self._session_manager
        agent_did = self._agent_did
        _orch_holder = [None]  # mutable list for late-binding

        async def _resolve_public_key(node_did: str):
            """解析 DID 公钥（复用 server 的解析逻辑）。"""
            from anp.authentication.did_wba import (
                resolve_did_wba_document,
                _extract_public_key,
                _find_verification_method,
            )
            logger.debug("[DID Resolve] 解析公钥: {}", node_did)

            if node_did == agent_did:
                # 本地 agent 公钥由外部注入（通过 cache_public_key）
                return tracer_ref._key_store.get(node_did)

            parts = node_did.split(":")
            if len(parts) < 4 or parts[1] != "wba":
                return None

            did_doc = None
            host_name = parts[2]
            if not host_name.endswith(".local"):
                try:
                    did_doc = await resolve_did_wba_document(node_did)
                except Exception:
                    pass

            if did_doc:
                key_id = f"{node_did}#key-1"
                method = _find_verification_method(did_doc, key_id)
                if method:
                    return _extract_public_key(method)
            return None

        async def _verify_back_record(
            prev_hop: dict, session_id: str, protocol_node_address: str,
        ) -> tuple[bool, str]:
            """回传验证：检查 PrevHop 与已存储 record 的一致性。"""
            if not session_id or not session_mgr:
                return True, ""
            session = session_mgr.get_or_create(session_id)
            stored = session.get_metadata("LastRecord")
            if not stored:
                return True, ""

            prev_node_did = prev_hop.get("node_did")
            if prev_node_did and prev_node_did not in tracer_ref._pub_key_cache:
                pub_key = await _resolve_public_key(prev_node_did)
                if pub_key:
                    tracer_ref.cache_public_key(prev_node_did, pub_key)

            ok, error = tracer_ref.verify_back_propagation(
                stored_hop=stored,
                prev_hop=prev_hop,
                session_id=session_id,
                protocol_node_address=protocol_node_address,
            )
            if not ok:
                logger.error(
                    "Back-propagation verification failed: session={}, error={}",
                    session_id, error,
                )
                session.set_metadata("VerifyStatus", f"FAILED: {error}")
            else:
                session.set_metadata("VerifyStatus", "OK")
            session_mgr.save(session)
            return ok, error

        @self._app.post("/record")
        async def receive_record(request: Request) -> JSONResponse:
            """接收并处理 record 消息。"""
            try:
                body = await request.json()
            except Exception:
                return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

            metadata = body.get("metadata") or {}
            session_id = metadata.get("Session_ID")
            protocol_node_address = metadata.get("Protocol_Node_Address")

            # 1. 保存 BehaviorEntry
            entry_data = metadata.get("BehaviorEntry")
            if entry_data:
                try:
                    await tracer_ref.save_behavior_entry(
                        session_id=session_id,
                        protocol_node_address=protocol_node_address,
                        node_did=entry_data["node_did"],
                        hop_count=entry_data.get("hop_count", 0),
                        field_type=entry_data["field_type"],
                        content=entry_data["content"],
                        target=entry_data.get("target", ""),
                        timestamp=entry_data.get("timestamp", 0),
                        extra=entry_data.get("extra"),
                    )
                    logger.info(
                        "BehaviorEntry saved from node={}, field={}",
                        entry_data.get("node_did"), entry_data.get("field_type"),
                    )
                except Exception as e:
                    logger.warning("Failed to save BehaviorEntry: {}", e)

                # 意图提取：首条 U2A (User→Agent) 消息作为用户意图来源
                if entry_data.get("field_type") == "U2A":
                    _orch_intent = _orch_holder[0]
                    if _orch_intent and session_id:
                        try:
                            await _orch_intent.on_field_U2A_recorded(
                                session_id, entry_data["content"],
                            )
                        except Exception as e:
                            logger.warning("Intent extraction failed: {}", e)

            # 2. 回传验证
            record_log = metadata.get("Record_Log")
            prev_hop = metadata.get("PrevHop")

            if record_log:
                record_log["session_id"] = session_id
                record_log["protocol_node_address"] = protocol_node_address

                if session_id and session_mgr:
                    if prev_hop and protocol_node_address:
                        await _verify_back_record(prev_hop, session_id, protocol_node_address)

                    session = session_mgr.get_or_create(session_id)
                    session.set_metadata("LastRecord", record_log)
                    session_mgr.save(session)

                logger.info("Record log saved")

                # 3. 触发分析
                _orch = _orch_holder[0]
                if _orch and session_id:
                    await _orch.on_record_received(session_id)

                return JSONResponse({"status": "Record saved"})

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
