""" ATTP 服务端 """

from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from anp.openanp import anp_agent, interface, AgentConfig
from anp.authentication.did_wba import (
    resolve_did_wba_document,
    _extract_public_key,
    _find_verification_method,
)
from typing import TYPE_CHECKING

from attp_channel.logging import get_logger, UVICORN_SILENT_LOG_CONFIG

logger = get_logger("Server")

from attp_channel.sessions import SessionManager
from attp_channel.sessions.node_message import NodeMessage
if TYPE_CHECKING:
    from attp_channel.config.config import ATTPServerConfig
    from attp_channel.protocol.tracer import MessageTracer


class ATTPServer:
    """ ATTP 服务端实现 """

    def __init__(
        self,
        agent_did: str,
        server_config: ATTPServerConfig,
        session_manager: SessionManager,
        web_callback=None,
        attp_channel_callback = None,
        tracer: MessageTracer = None,
        on_record_received=None,
    ):
        self._tracer = tracer
        self.session_manager = session_manager
        self._web_callback = web_callback
        self._attp_channel_callback = attp_channel_callback
        self._record_cb_holder = [on_record_received]
        self._running = False
        self._uvicorn_server = None
        self._serve_task = None

        self._apply_config(agent_did, server_config)

        # Create ATTP agent and FastAPI app
        self.agent_cls = self._create_agent()
        self.app = FastAPI()
        self.app.include_router(self.agent_cls.router())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_config(self, agent_did: str, server_config: ATTPServerConfig) -> None:
        """Update instance attributes from config (shared by __init__ and reload)."""
        self.agent_did = agent_did
        self.server_host = server_config.server_host
        self.server_port = server_config.server_port
        self.name = server_config.name
        self.prefix = server_config.prefix
        self.description = server_config.description
        self.private_key_path = Path(server_config.private_key_path).expanduser()
        self.public_key_path = Path(server_config.public_key_path).expanduser()

    def set_record_callback(self, callback) -> None:
        """Update the on_record_received callback (used by channel for analysis wiring)."""
        self._record_cb_holder[0] = callback

    async def _resolve_public_key_for_did(self, node_did: str):
        """异步解析 DID 对应的公钥。

        回退链：
        1. 本地 agent → 直接读 PEM 公钥文件
        2. 标准 DID 解析（DNS 可达时）
        """
        logger.debug(f"[DID Resolve] 开始解析公钥: {node_did}")

        # 本地 agent：读 PEM 公钥
        if node_did == self.agent_did:
            try:
                from cryptography.hazmat.primitives import serialization
                pem_data = self.public_key_path.read_bytes()
                try:
                    private_or_public = serialization.load_pem_private_key(pem_data, password=None)
                    pub = private_or_public.public_key()
                    logger.debug(f"[DID Resolve] 本地 agent,直接从 PEM 加载公钥成功")
                    return pub
                except ValueError:
                    pub = serialization.load_pem_public_key(pem_data)
                    logger.debug(f"[DID Resolve] 本地 agent,直接从 PEM 加载公钥成功")
                    return pub
            except Exception as e:
                logger.error("[DID Resolve] 本地公钥加载失败: {}", e)
                return None

        # 解析 DID 格式
        parts = node_did.split(":")
        if len(parts) < 4 or parts[1] != "wba":
            logger.error("[DID Resolve] 不支持的 DID 格式: {}", node_did)
            return None

        did_doc = None

        # 标准 DID 解析（仅对公网可达的 DID 尝试，避免 .local 等域名产生无意义 ERROR 日志）
        host = parts[2]
        if not host.endswith(".local"):
            logger.debug("[DID Resolve] 尝试标准 DNS 解析 https://{}(...)/did.json", host)
            try:
                did_doc = await resolve_did_wba_document(node_did)
                if did_doc:
                    logger.info("[DID Resolve] 成功: 标准解析获取到 DID 文档")
            except Exception as e:
                logger.debug("[DID Resolve] 失败: {}", e)
        else:
            logger.debug("[DID Resolve] 跳过: 主机名 {} 为本地域名，跳过标准 DNS 解析", host)

        # 提取公钥（支持 secp256k1/secp256r1/Ed25519）
        try:
            key_id = f"{node_did}#key-1"
            method = _find_verification_method(did_doc, key_id)
            if method:
                pub_key = _extract_public_key(method)
                logger.info("[DID Resolve] 公钥提取成功: {} (type={})", key_id, method.get('type'))
                return pub_key
            logger.error("[DID Resolve] DID 文档中未找到 {}", key_id)
            return None
        except Exception as e:
            logger.error("[DID Resolve] 公钥提取失败: {}", e)
            return None

    def _create_agent(self):
        """Create the ATTP agent class dynamically."""

        # 通过闭包捕获实例属性，供 Agent 内部方法使用
        session_manager = self.session_manager
        web_callback = self._web_callback
        attp_channel_callback = self._attp_channel_callback
        resolve_public_key = self._resolve_public_key_for_did
        active_tracer = self._tracer
        # Reference the instance-level mutable list so that
        # set_record_callback() updates are always visible here.
        _record_cb_holder = self._record_cb_holder

        async def _verify_back_record(prev_hop: dict, session_id: str, origin_did: str) -> tuple[bool, str]:
            """回传验证：检查 PrevHop 与已存储 record 的一致性。

            Returns:
                (True, "") 验证通过或无需验证。
                (False, error_desc) 验证失败。
            """
            if not session_id or not session_manager:
                return True, ""
            session = session_manager.get_or_create(session_id)
            stored = session.get_metadata("LastRecord")
            if not stored:
                return True, ""

            # 预解析 prev_hop 节点的公钥
            prev_node_did = prev_hop.get("node_did")
            if prev_node_did and prev_node_did not in active_tracer._pub_key_cache:
                pub_key = await resolve_public_key(prev_node_did)
                if pub_key:
                    active_tracer.cache_public_key(prev_node_did, pub_key)

            ok, error = active_tracer.verify_back_propagation(
                stored_hop=stored,
                prev_hop=prev_hop,
                session_id=session_id,
                origin_did=origin_did,
            )
            if not ok:
                logger.error(
                    "Back-propagation verification failed: session={}, error={}",
                    session_id, error,
                )
                session.set_metadata("VerifyStatus", f"FAILED: {error}")
            else:
                session.set_metadata("VerifyStatus", "OK")
            session_manager.save(session)
            return ok, error


        @anp_agent(AgentConfig(
            name=self.name,
            did=self.agent_did,
            prefix=self.prefix,
            description=self.description,
        ))
        class Agent:

            @interface
            async def health(self) -> str:
                """健康检查端点，返回 'ok' 表示服务正常。"""
                return "ok"

            @interface
            async def receive_message(
                self,
                sender_did: str,
                content: str,
                message_type: str,
                metadata: dict | None = None,
            ) -> str:
                """接收来自其他 Agent 的 ATTP 消息。

                Args:
                    sender_did: 发送者 DID
                    content: 消息内容
                    message_type: 消息类型 (agent_request / record)
                    metadata: 附加元数据

                Returns:
                    处理结果
                """
                # 处理 record 类型消息
                if message_type == "record":
                    metadata = metadata or {}
                    record_log = metadata.get("Record_Log")
                    prev_hop = metadata.get("PrevHop")
                    session_id = metadata.get("Session_ID")
                    origin_did = metadata.get("Origin_DID")

                    # Extract and persist NodeMessage from remote node
                    node_msg_data = metadata.get("NodeMessage")
                    if node_msg_data:
                        try:
                            node_message = NodeMessage.from_dict(node_msg_data)
                            await active_tracer.save_node_message(node_message)
                            logger.info(
                                "NodeMessage saved from node={}, hop={}",
                                node_message.node_did, node_message.hop_count,
                            )
                        except Exception as e:
                            logger.warning("Failed to save NodeMessage: {}", e)

                    if record_log:
                        # 注入 origin_did and session_id 到 record_log，供后续验证使用
                        record_log["session_id"] = session_id
                        record_log["origin_did"] = origin_did

                        # 回传验证：与上次存储的 record 交叉比对
                        if session_id and origin_did and session_manager:
                            await _verify_back_record(prev_hop, session_id, origin_did)

                            # 存储当前 record 供下次验证使用
                            session = session_manager.get_or_create(session_id)
                            session.set_metadata("LastRecord", record_log)
                            session_manager.save(session)

                        logger.info("Record log saved from {}", sender_did)

                        # Notify analysis trigger
                        _record_cb = _record_cb_holder[0]
                        if _record_cb and session_id:
                            await _record_cb(session_id)

                        return "Record saved"
                    return "Error: No log in record metadata"

                if message_type == "agent_request":                    
                    try:
                        session_id = metadata.get("Session_ID")

                        # Store trace metadata (Hop, Session_ID, Origin_DID only)
                        if session_id and session_manager:
                            session = session_manager.get_or_create(session_id)
                            session.set_trace_metadata(metadata)
                            session_manager.save(session)
                            logger.debug(
                                "Session stored/updated: id={}, sender={}, metadata keys={}",
                                session_id, sender_did, list(session.metadata.keys()),
                            )
                        if attp_channel_callback:
                            await attp_channel_callback(
                                sender=sender_did,
                                chat_id=session_id,
                                content=content,
                                media=[],
                            )
                        
                        # Notify UI of incoming node message
                        if web_callback:
                            await web_callback(content, {
                                "is_node_message": True,
                                "direction": "in",
                                "other_did": sender_did,
                                "Session_ID": metadata.get("Session_ID"),
                            })
                        return "Message received"
                    except Exception as e:
                        logger.error("Error processing ATTP message: {}", e)
                        return f"Error: {str(e)}"

        return Agent

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Start the ATTP server (non-blocking)."""
        cfg = uvicorn.Config(
            self.app,
            host=self.server_host,
            port=self.server_port,
            log_level="info",
            log_config=UVICORN_SILENT_LOG_CONFIG,
        )
        self._uvicorn_server = uvicorn.Server(cfg)
        self._serve_task = asyncio.create_task(self._uvicorn_server.serve())
        logger.info("started at {}:{}", self.server_host, self.server_port)
        self._running = True

    async def stop(self):
        """Stop the ATTP server gracefully."""
        self._running = False
        if self._uvicorn_server:
            self._uvicorn_server.should_exit = True
        if self._serve_task:
            # Wait for graceful shutdown first (lets uvicorn close sockets properly)
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

    async def reload(self, server_config: ATTPServerConfig, agent_did: str) -> None:
        """Stop → update config → rebuild verifier/agent/app → start."""
        await self.stop()
        self._apply_config(agent_did, server_config)

        self.agent_cls = self._create_agent()
        self.app = FastAPI()
        self.app.include_router(self.agent_cls.router())

        # Wait until the port is actually available before starting
        # Check 0.0.0.0 (superset) since uvicorn may bind to it regardless of config
        await self._wait_for_port("0.0.0.0", self.server_port, timeout=10.0)
        await self.start()
        logger.info("reloaded on {}:{}", self.server_host, self.server_port)

    @staticmethod
    async def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
        """Poll until the port is available for binding."""
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((host, port))
                return
            except OSError:
                if asyncio.get_event_loop().time() >= deadline:
                    raise
                await asyncio.sleep(0.3)
