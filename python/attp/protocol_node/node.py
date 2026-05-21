"""ProtocolNode — 协议节点主类，管理单端口生命周期。

自包含设计：传入 config_path 即可，内部自行加载配置、创建所有依赖组件。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from attp.app.logging import get_logger
from attp.core.sessions.protocol_node import ProtocolSessionManager
from attp.core.pn_tracer import ProtocolTracer
from attp.core.authentication import DIDResolver
from attp.protocol_node.config.config import ProtocolNodeConfigFile
from attp.protocol_node.engine.behavior_controller import BehaviorController
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector

if TYPE_CHECKING:
    from attp.core.analysis.orchestrator import AnalysisOrchestrator

logger = get_logger("ProtocolNode")


class ProtocolNode:
    """协议节点：单端口（ProtocolPort）对外服务。

    使用方式::

        node = ProtocolNode(config_path="~/.attp/protocol_node/config.json")
        await node.start()
        ...
        await node.stop()
    """

    def __init__(self, config_path: str | Path):
        self._config_path = Path(config_path).expanduser()

        # 加载配置（同步）
        self._config = ProtocolNodeConfigFile.load(self._config_path)

        # 以下组件在 start() 中异步创建
        self._tracer: ProtocolTracer | None = None
        self._session_manager: ProtocolSessionManager | None = None
        self._port = None
        self._orchestrator: AnalysisOrchestrator | None = None
        self._sweep_task: asyncio.Task | None = None
        self._malicious_detector: MaliciousNodeDetector | None = None

    @property
    def config(self) -> ProtocolNodeConfigFile:
        """当前生效的配置（只读）。"""
        return self._config

    @property
    def tracer(self) -> ProtocolTracer | None:
        """已创建的 ProtocolTracer（start() 之后可用）。"""
        return self._tracer

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """加载配置 → 创建所有组件 → 启动单端口。"""
        cfg = self._config

        # 1. 创建 ProtocolTracer
        db_path = cfg.get_db_path()
        self._tracer = await ProtocolTracer.create(db_path=db_path)

        # 2. 创建 SessionManager（注入 storage 以启用验证状态持久化）
        self._session_manager = ProtocolSessionManager(storage=self._tracer.storage)

        # 3. 创建 DIDResolver + BehaviorController + MaliciousNodeDetector
        did_resolver = DIDResolver(
            key_store=self._tracer.key_store,
        )
        behavior_controller = BehaviorController()
        malicious_detector = MaliciousNodeDetector(did_resolver)
        self._malicious_detector = malicious_detector

        # 4. 创建统一 ProtocolPort
        from attp.protocol_node.ports.protocol_port import ProtocolPort

        web = cfg.web
        self._port = ProtocolPort(
            tracer=self._tracer,
            session_manager=self._session_manager,
            host=web.host,
            port=web.port,
            did_resolver=did_resolver,
            behavior_controller=behavior_controller,
            malicious_detector=malicious_detector,
        )

        # 5. 可选：创建 AnalysisOrchestrator
        self._orchestrator = self._build_orchestrator()
        if self._orchestrator:
            self._port.set_orchestrator(self._orchestrator)

        # 6. 启动端口
        await self._port.start()

        # 7. 启动过期 PendingMessage 周期扫描
        self._sweep_task = asyncio.create_task(self._periodic_sweep())

        logger.info(
            "ProtocolNode started: port={}:{}",
            web.host, web.port,
        )

    async def stop(self) -> None:
        """停止端口服务。"""
        if self._sweep_task:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None
        if self._port:
            await self._port.stop()
        logger.info("ProtocolNode stopped")

    # ------------------------------------------------------------------
    # 过期 PendingMessage 周期扫描
    # ------------------------------------------------------------------

    async def _periodic_sweep(self) -> None:
        """每 60 秒扫描所有 session 的过期 PendingMessage，进行单回传判定。"""
        try:
            while True:
                await asyncio.sleep(60)
                if not self._session_manager or not self._malicious_detector or not self._tracer:
                    continue
                for session in list(self._session_manager._sessions.values()):
                    expired = session.pop_expired_pending_messages()
                    for _nonce, msg in expired:
                        report = await self._malicious_detector.evaluate_single_back_prop(
                            msg, session,
                        )
                        if report:
                            await self._tracer.save_malicious_report(report)
                    if expired:
                        await self._session_manager.save(session)
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Orchestrator 管理
    # ------------------------------------------------------------------

    def set_orchestrator(self, orchestrator: AnalysisOrchestrator | None) -> None:
        """注入或清除 AnalysisOrchestrator。"""
        self._orchestrator = orchestrator
        if self._port:
            self._port.set_orchestrator(orchestrator)
        if orchestrator:
            logger.info("AnalysisOrchestrator injected into ProtocolNode")
        else:
            logger.info("AnalysisOrchestrator cleared from ProtocolNode")

    async def reload_config(self) -> None:
        """重新加载配置文件并重建 Orchestrator。

        注意：端口变更需要手动重启 ProtocolNode。
        """
        old_cfg = self._config
        self._config = ProtocolNodeConfigFile.load(self._config_path)

        # 端口变更检测
        if (
            old_cfg.web.host != self._config.web.host
            or old_cfg.web.port != self._config.web.port
        ):
            logger.warning(
                "ProtocolNode 端口配置已变更，需要手动重启才能生效 (old={}, new={})",
                old_cfg.web.model_dump(),
                self._config.web.model_dump(),
            )

        # Analysis 变更 → 重建 orchestrator
        self._orchestrator = self._build_orchestrator()
        self.set_orchestrator(self._orchestrator)
        logger.info("ProtocolNode 配置热重载完成")

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _build_orchestrator(self):
        """根据当前配置构建 AnalysisOrchestrator，未启用则返回 None。"""
        analysis_cfg = self._config.analysis
        if not analysis_cfg.enabled or not analysis_cfg.api_key:
            return None

        from attp.core.analysis import SemanticTaintAnalyzer, AnalysisOrchestrator

        analyzer = SemanticTaintAnalyzer(
            api_key=analysis_cfg.api_key,
            base_url=analysis_cfg.base_url,
            model=analysis_cfg.model,
        )
        logger.info(
            "Semantic taint analysis enabled (model={}, batch_size={})",
            analysis_cfg.model,
            analysis_cfg.report_batch_size,
        )
        return AnalysisOrchestrator(
            analyzer=analyzer,
            session_manager=self._session_manager,
            tracer=self._tracer,
            batch_size=analysis_cfg.report_batch_size,
        )