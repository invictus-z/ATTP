"""CLI entry point for standalone Protocol Node mode.

Usage:
    # 使用配置文件启动
    attp protocol-node start --config path/to/config.json

    # 生成默认配置文件
    attp protocol-node init-config [--output path/to/config.json]
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

from attp.app.logging import set_log_level
set_log_level("DEBUG")

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
        "--config", default="~/.attp/protocol_node/config.json",
        help="Path to config file (default: ~/.attp/protocol_node/config.json)",
    )

    # --- init-config 子命令 ---
    init_parser = pn_sub.add_parser("init-config", help="Generate a default config file")
    init_parser.add_argument(
        "--output", default="~/.attp/protocol_node/config.json",
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
    from attp.protocol_node import ProtocolNode

    node = ProtocolNode(config_path=args.config)
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