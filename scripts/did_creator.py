"""DID 文档与密钥对生成工具

基于 anp 的 create_did_wba_document 为指定的 Agent 批量生成 DID 文档及密钥文件。

生成的密钥类型：
  - key-1: Ed25519（用于 DID 认证）
  - key-2: secp256r1（用于 E2EE 消息签名）
  - key-3: X25519（用于 E2EE 密钥协商）
"""

import argparse
import json
import sys
from pathlib import Path

from anp.authentication import create_did_wba_document


def generate_did(hostname: str, name: str, node_type: str, output_dir: Path) -> None:
    """为单个 Agent 生成 DID 文档和密钥文件。"""
    attp_service = {
        "id": "#node-type",
        "type": "ATTPNodeType",
        "serviceEndpoint": f"attp:type:{node_type}",
    }
    did_document, keys = create_did_wba_document(
        hostname=hostname,
        path_segments=[name],
        services=[attp_service],
    )

    agent_dir = output_dir / name
    agent_dir.mkdir(parents=True, exist_ok=True)

    with open(agent_dir / "did.json", "w", encoding="utf-8") as f:
        json.dump(did_document, f, indent=2, ensure_ascii=False)

    for fragment, (private_bytes, public_bytes) in keys.items():
        with open(agent_dir / f"{fragment}_private.pem", "wb") as f:
            f.write(private_bytes)
        with open(agent_dir / f"{fragment}_public.pem", "wb") as f:
            f.write(public_bytes)

    print(f"  ✓ {name} -> {agent_dir} (type={node_type})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="为 ATTP Agent 批量生成 DID 文档与密钥对",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
生成的密钥类型：
  key-1  secp256k1  用于 DID 认证
  key-2  secp256r1  用于 E2EE 消息签名
  key-3  X25519     用于 E2EE 密钥协商

示例：
  python scripts/did_creator.py --hostname did-server.test --names userA userB --type agent
  python scripts/did_creator.py --hostname did-server.test --names my-agent --output-dir ~/.attp/agent/nanobot/did
""",
    )
    parser.add_argument(
        "--hostname",
        default="did-server.test",
        help="DID 服务器主机名（默认: did-server.test）",
    )
    parser.add_argument(
        "--names",
        nargs="+",
        required=True,
        metavar="NAME",
        help="Agent 名称列表（至少一个）",
    )
    parser.add_argument(
        "--output-dir",
        default="./did_output",
        help="输出根目录（默认: ./did_output）",
    )
    parser.add_argument(
        "--type",
        dest="node_type",
        choices=["agent", "tool", "user"],
        default="agent",
        help="节点身份角色（默认: agent）",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    print(f"生成 DID 文档至: {output_dir}\n")

    for name in args.names:
        generate_did(args.hostname, name, args.node_type, output_dir)

    print(f"\n共生成 {len(args.names)} 个 Agent 的 DID 文档与密钥。")


if __name__ == "__main__":
    main()