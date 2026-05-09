"""CLI entry point for standalone Protocol Node mode.

Usage:
    # 使用配置文件启动
    attp protocol-node start --config path/to/config.json

    # 使用命令行参数启动（覆盖配置文件）
    attp protocol-node start --data-port PORT --api-port PORT [--host HOST] [--db-path PATH]

    # 生成默认配置文件
    attp protocol-node init-config [--output path/to/config.json]
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="attp", description="ATTP Protocol Node CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    pn_parser = subparsers.add_parser("protocol-node", help="Protocol Node operations")
    pn_sub = pn_parser.add_subparsers(dest="action")

    # --- start 子命令 ---
    start_parser = pn_sub.add_parser("start", help="Start Protocol Node")
    start_parser.add_argument(
        "--config", default="~/.nanobot/attp/protocol_node_config.json",
        help="Path to config file (default: ~/.nanobot/attp/protocol_node_config.json)",
    )
    start_parser.add_argument(
        "--data-port", type=int, default=None,
        help="Data port number (overrides config file)",
    )
    start_parser.add_argument(
        "--api-port", type=int, default=None,
        help="API port number (overrides config file)",
    )
    start_parser.add_argument(
        "--host", default=None,
        help="Host to bind (overrides config file)",
    )
    start_parser.add_argument(
        "--db-path", default=None,
        help="SQLite database path (overrides config file)",
    )

    # --- init-config 子命令 ---
    init_parser = pn_sub.add_parser("init-config", help="Generate a default config file")
    init_parser.add_argument(
        "--output", default="~/.nanobot/attp/protocol_node_config.json",
        help="Output path for the config file",
    )

    args = parser.parse_args()

    if args.command == "protocol-node":
        if args.action == "start":
            asyncio.run(_run_standalone(args))
        elif args.action == "init-config":
            _init_config(args)
        else:
            pn_parser.print_help()
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


def _init_config(args) -> None:
    from attp.protocol_node.config.config import ProtocolNodeConfigFile

    cfg = ProtocolNodeConfigFile()
    cfg.save(args.output)
    print(f"Config file generated at: {args.output}")


async def _run_standalone(args):
    from pathlib import Path

    from attp.protocol_node import ProtocolNode
    from attp.protocol_node.config.config import ProtocolNodeConfigFile
    from attp.core.sessions import SessionManager
    from attp.core.tracer import MessageTracer

    # 1. 加载配置文件
    cfg = ProtocolNodeConfigFile.load(args.config)

    # 2. CLI 参数覆盖配置文件值
    if args.host is not None:
        cfg.protocol_node.data_port_host = args.host
        cfg.protocol_node.api_port_host = args.host
    if args.data_port is not None:
        cfg.protocol_node.data_port_port = args.data_port
    if args.api_port is not None:
        cfg.protocol_node.api_port_port = args.api_port
    if args.db_path is not None:
        cfg.storage.db_path = args.db_path

    # 3. 验证必填项
    pn = cfg.protocol_node
    if pn.data_port_port == 0 or pn.api_port_port == 0:
        print("Error: data-port and api-port must be specified via config file or CLI args")
        sys.exit(1)

    # 4. 拼接数据库路径
    db_path = str(Path(cfg.storage.data_dir).expanduser() / cfg.storage.db_path)

    # 5. 构建组件
    tracer = await MessageTracer.create(db_path=db_path)
    session_manager = SessionManager()

    node = ProtocolNode(
        data_port_host=pn.data_port_host,
        data_port_port=pn.data_port_port,
        api_port_host=pn.api_port_host,
        api_port_port=pn.api_port_port,
        tracer=tracer,
        session_manager=session_manager,
        agent_did=cfg.agent_did,
    )

    # 6. 可选：构建 AnalysisOrchestrator
    if cfg.analysis.enabled and cfg.analysis.api_key:
        from attp.core.analysis import SemanticTaintAnalyzer, AnalysisOrchestrator

        analyzer = SemanticTaintAnalyzer(
            api_key=cfg.analysis.api_key,
            base_url=cfg.analysis.base_url,
            model=cfg.analysis.model,
        )
        orchestrator = AnalysisOrchestrator(
            analyzer=analyzer,
            session_manager=session_manager,
            tracer=tracer,
            batch_size=cfg.analysis.report_batch_size,
        )
        node.set_orchestrator(orchestrator)

    await node.start()

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    print("Protocol Node running. Press Ctrl+C to stop.")
    await stop_event.wait()
    await node.stop()


if __name__ == "__main__":
    main()
