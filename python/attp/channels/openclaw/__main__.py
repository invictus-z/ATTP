"""Entry point: python -m attp.channels.openclaw

Spawned by the openclaw Node channel plugin (gateway.startAccount) with:
    <pythonPath> -m attp.channels.openclaw --config <cfg> --webhook <url> --token <tok>
"""
from __future__ import annotations

import argparse
import asyncio
import signal

from attp.channels.openclaw import OpenclawATTPAdapter


def main() -> None:
    parser = argparse.ArgumentParser(prog="attp.channels.openclaw")
    parser.add_argument("--config", required=True, help="ATTP openclaw profile config path")
    parser.add_argument("--webhook", required=True, help="openclaw inbound webhook URL")
    parser.add_argument("--token", default="", help="shared bearer token for the webhook")
    args = parser.parse_args()

    adapter = OpenclawATTPAdapter(
        config_path=args.config, webhook_url=args.webhook, token=args.token
    )

    loop = asyncio.new_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, adapter.stop)
        except NotImplementedError:
            # Windows: add_signal_handler unsupported; the host supervisor SIGTERM-kills.
            break

    try:
        loop.run_until_complete(adapter.run())
    except KeyboardInterrupt:
        adapter.stop()
    finally:
        loop.close()


if __name__ == "__main__":
    main()
