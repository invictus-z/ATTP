"""ATTP 工具节点 Demo — 计算器示例。

启动一个持续运行的 ATTPToolNode，注册 add 工具（计算 A+B），
等待外部连接测试。

用法:
    python test/demo_tool_node.py

端点:
    GET  http://127.0.0.1:9000/attp/health     — 健康检查
    GET  http://127.0.0.1:9000/attp/ad.json    — 工具描述
    POST http://127.0.0.1:9000/attp            — 调用工具

测试示例:
    curl http://127.0.0.1:9000/attp/health
    curl http://127.0.0.1:9000/attp/ad.json
    curl -X POST http://127.0.0.1:9000/attp -H "Content-Type: application/json" -d "{\"message_type\":\"tool_request\",\"sender_did\":\"did:wba:test:sender\",\"tool_name\":\"add\",\"arguments\":\"{\\\"a\\\":3,\\\"b\\\":5}\"}"
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "python"))

from attp.sdk.tools import ATTPToolNode


# ── 固定配置 ──────────────────────────────────────────────────────────

DID = "did:wba:did-server.test:demo-tool"
NAME = "demo-tool"
HOST = "0.0.0.0"
PORT = 9000


async def main():
    node = ATTPToolNode(
        did=DID,
        name=NAME,
        host=HOST,
        port=PORT,
        db_path=":memory:",
    )

    @node.tool(
        "add",
        "计算两个数的和",
        {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "第一个数"},
                "b": {"type": "number", "description": "第二个数"},
            },
            "required": ["a", "b"],
        },
    )
    async def add(a: float, b: float):
        return {"result": a + b, "expression": f"{a} + {b} = {a + b}"}

    print(f"ATTP Tool Node Demo — 计算器 (A+B)")
    print(f"  DID:   {node.did}")
    print(f"  Name:  {node.name}")
    print(f"  Key:   {node.private_key_path}")
    print(f"  Tools: [add]")
    print()
    print(f"端点:")
    print(f"  GET  http://{HOST}:{PORT}/attp/health")
    print(f"  GET  http://{HOST}:{PORT}/attp/ad.json")
    print(f"  POST http://{HOST}:{PORT}/attp")
    print()
    print("按 Ctrl+C 停止")

    await node.start()

    # 保持运行
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await node.stop()
        print("\n已停止")


if __name__ == "__main__":
    asyncio.run(main())