from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from attp_channel.logging import get_logger

logger = get_logger("Channel")

from pydantic import Field

from nanobot.channels.base import BaseChannel
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import Base

from attp_channel.client import ATTPClient
from attp_channel.server import ATTPServer
from attp_channel.config import ConfigManager
from attp_channel.heartbeat import HeartbeatManager
from attp_channel.web_app import WebApp
from attp_channel.sessions import SessionManager
from attp_channel.tools import SendMessageTool
from attp_channel.protocol.tracer import MessageTracer

if TYPE_CHECKING:
    from attp_channel.config.config import ATTPConfigFile


class ATTPConfig(Base):
    """ATTP channel configuration."""
    enabled: bool = False
    config_path: str = "~/.nanobot/attp_config.json"
    allow_from: list[str] = Field(default_factory=lambda: ["*"])


class ATTPChannel(BaseChannel):
    name = "attp"
    display_name = "ATTP"

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = ATTPConfig(**config)
        super().__init__(config, bus)

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return ATTPConfig().model_dump(by_alias=True)

    async def start(self) -> None:
        """
        启动 ATTP channel
        """
        self._running = True
        config_path = self.config.config_path

        # 构建ConfigManager
        self._config_manager = ConfigManager(config_path)
        self._config_manager.load()
        self._attp_cfg = self._config_manager.attp_config

        # 构建Tracer
        storage_cfg = self._attp_cfg.storage
        tracer_db_path = str(Path(storage_cfg.data_dir).expanduser() / storage_cfg.db_path)
        self._tracer = MessageTracer(db_path=tracer_db_path)

        # 构建后端服务器 web_app/
        self._web_app = WebApp(
            web_config=self._attp_cfg.web_app,
            channel_callback=self._receive,
            tracer=self._tracer,
        )

        # 构建SessionManager
        self._session_manager = SessionManager()

        # 构建语义污点分析器
        self._analyzer = None
        analysis_cfg = self._attp_cfg.analysis
        if analysis_cfg.enabled and analysis_cfg.api_key:
            from attp_channel.analysis import SemanticTaintAnalyzer
            self._analyzer = SemanticTaintAnalyzer(
                api_key=analysis_cfg.api_key,
                base_url=analysis_cfg.base_url,
                model=analysis_cfg.model,
            )
            self._analysis_batch_size = analysis_cfg.report_batch_size
            logger.info("Semantic taint analysis enabled (model={}, batch_size={})",
                        analysis_cfg.model, analysis_cfg.report_batch_size)
        else:
            self._analysis_batch_size = 10

        # 构建所有组件
        self._attp_client = ATTPClient(
            agent_did=self._attp_cfg.did,
            client_config=self._attp_cfg.attp_client,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message,
            tracer=self._tracer,
        )
        self._attp_server = ATTPServer(
            agent_did=self._attp_cfg.did,
            server_config=self._attp_cfg.attp_server,
            session_manager=self._session_manager,
            web_callback = self._web_app.record_message,
            attp_channel_callback = self._receive,
            tracer=self._tracer,
            on_record_received=self._on_record_received,
        )
        self._heartbeat_manager = HeartbeatManager(
            heartbeat_config=self._attp_cfg.heartbeat,
            attp_client=self._attp_client,
        )
        self._send_message_tool = SendMessageTool(
            tool_config=self._attp_cfg.tool,
            callback = self._attp_client.send_message
        )

        # Wire analysis callbacks into WebApp
        self._web_app._on_field_c_recorded = self._on_field_c_recorded
        self._web_app._on_session_end = self._on_session_end

        # 并发启动所有组件 启动阶段无依赖关系
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._attp_client.start())
            tg.create_task(self._attp_server.start())
            tg.create_task(self._heartbeat_manager.start())
            tg.create_task(self._send_message_tool.start())
            tg.create_task(self._web_app.start(
                self._attp_client, self._config_manager,
                reload_callback=self.reload,
                session_manager=self._session_manager,
                agent_did=self._attp_cfg.did,
            ))

        # start() must block forever (or until stop() is called).
        while self._running:
            await asyncio.sleep(1)

        # 并发停止所有组件
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._heartbeat_manager.stop())
            tg.create_task(self._send_message_tool.stop())
            tg.create_task(self._attp_client.stop())
            tg.create_task(self._attp_server.stop())
            tg.create_task(self._web_app.stop())

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        """Send message back to UI via WebSocket (called by ChannelManager)."""
        msg.metadata["Session_ID"] = msg.chat_id
        await self._web_app.record_message(msg.content, msg.metadata)

    async def _receive(self, sender: str, chat_id: str, content: str, media: list[str]) -> str:
        await self._handle_message(
            sender_id=sender,
            chat_id=chat_id,
            content=content,
            media=media,
        )
        return "ok"

    async def reload(self, old_cfg: ATTPConfigFile, new_cfg: ATTPConfigFile) -> None:
        """Hot-reload only the components whose config has changed.

        WebApp host/port changes are logged as warnings (requires manual restart).
        """
        # DID or ATTPClient config changed
        if old_cfg.did != new_cfg.did or old_cfg.attp_client.changed_fields(new_cfg.attp_client):
            logger.info("ATTPClient config changed, reloading...")
            await self._attp_client.reload(new_cfg.attp_client, new_cfg.did)

        # ATTPServer config changed (also triggers on DID change)
        if old_cfg.did != new_cfg.did or old_cfg.attp_server.changed_fields(new_cfg.attp_server):
            logger.info("ATTPServer config changed, reloading...")
            await self._attp_server.reload(new_cfg.attp_server, new_cfg.did)

        # Heartbeat config changed
        if old_cfg.heartbeat.changed_fields(new_cfg.heartbeat):
            logger.info("Heartbeat config changed, reloading...")
            await self._heartbeat_manager.reload(new_cfg.heartbeat)

        # Tool config changed
        if old_cfg.tool.changed_fields(new_cfg.tool):
            logger.info("SendMessageTool config changed, reloading...")
            await self._send_message_tool.reload(new_cfg.tool)

        # Analysis config changed
        if old_cfg.analysis.changed_fields(new_cfg.analysis):
            logger.info("Analysis config changed, rebuilding analyzer...")
            analysis_cfg = new_cfg.analysis
            if analysis_cfg.enabled and analysis_cfg.api_key:
                from attp_channel.analysis import SemanticTaintAnalyzer
                self._analyzer = SemanticTaintAnalyzer(
                    api_key=analysis_cfg.api_key,
                    base_url=analysis_cfg.base_url,
                    model=analysis_cfg.model,
                )
                self._analysis_batch_size = analysis_cfg.report_batch_size
            else:
                self._analyzer = None
            logger.info("Analyzer reloaded: enabled={}", new_cfg.analysis.enabled)

        # WebApp config changed — cannot restart self, just update attributes
        if old_cfg.web_app.changed_fields(new_cfg.web_app):
            self._web_app.host = new_cfg.web_app.host
            self._web_app.port = new_cfg.web_app.port
            logger.warning(
                "WebApp host/port changed to {}:{} — requires manual restart",
                new_cfg.web_app.host, new_cfg.web_app.port,
            )

        self._attp_cfg = new_cfg
        logger.info("hot-reload complete")

    # ------------------------------------------------------------------
    # Semantic taint analysis orchestration
    # ------------------------------------------------------------------

    async def _on_field_c_recorded(self, session_id: str, content: str) -> None:
        """Called when a User→Agent message (field c) is recorded.

        Extracts intent on the first user message of a session.
        """
        if not self._analyzer:
            return
        session = self._session_manager.get_or_create(session_id)
        if session.get_intent():
            return  # intent already extracted

        intent = await self._analyzer.extract_intent(content)
        if intent:
            session.set_intent(intent.to_dict())
            self._session_manager.save(session)
            logger.info("Intent extracted for session={}", session_id)

    async def _on_record_received(self, session_id: str) -> None:
        """Called by server when a record message is received.

        Increments report counter and triggers analysis if batch size reached.
        """
        if not self._analyzer:
            return
        session = self._session_manager.get_or_create(session_id)
        count = session.increment_report_count()
        self._session_manager.save(session)

        if count >= self._analysis_batch_size:
            logger.info(
                "Report batch size reached ({}/{}), triggering analysis for session={}",
                count, self._analysis_batch_size, session_id,
            )
            await self._run_analysis(session_id, is_final=False)

    async def _on_session_end(self, session_id: str) -> None:
        """Called when a session ends (user starts new session, disconnects, or explicit end).

        Runs final analysis on any remaining unchecked traces.
        """
        if not self._analyzer:
            return
        session = self._session_manager.get(session_id)
        if not session:
            return
        state = session.get_analysis_state()
        if state["report_count"] > 0:
            logger.info("Session {} ending, running final analysis", session_id)
            await self._run_analysis(session_id, is_final=True)

    async def _run_analysis(self, session_id: str, is_final: bool = False) -> None:
        """Run semantic taint analysis for a session.

        Recovers unchecked traces, calls LLM, and updates state.
        """
        session = self._session_manager.get_or_create(session_id)
        state = session.get_analysis_state()
        intent_data = state.get("intent")

        if not intent_data:
            logger.warning("Cannot run analysis for session={}: no intent extracted", session_id)
            return

        from attp_channel.analysis.models import IntentDescriptor
        intent = IntentDescriptor.from_dict(intent_data)

        # Recover unchecked traces
        last_id = state["last_trace_id"]
        traces, max_id = self._tracer.recover_traces_since(session_id, last_id)

        if not traces:
            session.reset_report_count()
            self._session_manager.save(session)
            return

        batch_index = state["batch_index"] + 1
        previous_context = state["context"]

        logger.info(
            "Running analysis: session={}, batch={}, traces={}, is_final={}",
            session_id, batch_index, len(traces), is_final,
        )

        report = await self._analyzer.analyze(
            session_id=session_id,
            batch_index=batch_index,
            from_trace_id=last_id,
            to_trace_id=max_id,
            traces=traces,
            intent=intent,
            previous_context=previous_context,
        )

        # Persist report
        report_json = json.dumps(report.to_dict(), ensure_ascii=False)
        self._tracer.save_analysis_report(report_json, report.context_summary)

        # Update session state
        session.reset_report_count()
        session.update_analysis_cursor(
            batch_index=batch_index,
            last_trace_id=max_id,
            context=report.context_summary,
        )
        self._session_manager.save(session)

        # Notify user if suspicious or malicious
        if report.overall_verdict in ("suspicious", "malicious"):
            await self._notify_analysis_result(session_id, report)

        logger.info(
            "Analysis complete: session={}, verdict={}, nodes_checked={}",
            session_id, report.overall_verdict, len(report.node_verdicts),
        )

    async def _notify_analysis_result(self, session_id: str, report) -> None:
        """Push analysis result to the WebUI as a system notification."""
        verdict = report.overall_verdict
        summary = report.summary
        malicious_nodes = [
            v.node_did for v in report.node_verdicts
            if v.severity in ("medium", "high")
        ]
        notification = (
            f"[Security Alert] Semantic Taint Analysis detected: {verdict}\n"
            f"Summary: {summary}\n"
        )
        if malicious_nodes:
            notification += f"Suspicious nodes: {', '.join(malicious_nodes)}"

        await self._web_app.record_message(notification, {
            "Session_ID": session_id,
            "is_analysis_alert": True,
            "verdict": verdict,
            "summary": summary,
        })
