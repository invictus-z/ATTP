"""DID 文档与密钥对生成工具

基于 anp 的 create_did_wba_document 生成 DID 文档及密钥文件。

生成的密钥类型：
  key-1  Ed25519     用于 DID 认证
  key-2  secp256r1   用于 E2EE 消息签名
  key-3  X25519      用于 E2EE 密钥协商

两种用法（二选一）：

  1) 多段路径（推荐，匹配 examples 的 test:agent:nanobot 等结构）：

       python scripts/did_creator.py --hostname attp-diting.cn --type agent \\
           --path-segments test agent nanobot --output-dir examples/.attp/agent/nanobot/did

     生成 did:wba:attp-diting.cn:test:agent:nanobot:e1_<keyid>，
     did.json + key-1/2/3 直接写入 --output-dir。

  2) 批量单段（遗留；每个 name 一条单段 DID，输出到 output-dir/<name>/）：

       python scripts/did_creator.py --hostname did-server.test --names userA userB
       python scripts/did_creator.py --hostname did-server.test --names my-agent --output-dir ~/.attp/agent/nanobot/did

生成后需把 did.json 中的 id 回填到对应 config.json 的 did 字段。
"""

import argparse
import json
import sys
from pathlib import Path

from anp.authentication import create_did_wba_document


def _service_for(node_type: str) -> list:
    """ATTPNodeType service，标注节点角色（agent/tool/user）。"""
    return [{"id": "#node-type", "type": "ATTPNodeType", "serviceEndpoint": f"attp:type:{node_type}"}]


def generate_one(hostname: str, path_segments: list[str], node_type: str, output_dir: Path) -> str:
    """生成单个 DID 文档 + 密钥，直接写入 output_dir。返回生成的 DID id。"""
    doc, keys = create_did_wba_document(
        hostname=hostname,
        path_segments=path_segments,
        services=_service_for(node_type),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "did.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    for fragment, (private_bytes, public_bytes) in keys.items():
        (output_dir / f"{fragment}_private.pem").write_bytes(private_bytes)
        (output_dir / f"{fragment}_public.pem").write_bytes(public_bytes)
    return doc["id"]


def main() -> None:
    # Windows 默认控制台编码（GBK）无法打印 ✓ 等 Unicode 字符，统一重配为 UTF-8。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="生成 ATTP DID 文档与密钥对（支持多段路径）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--hostname", required=True, help="DID 服务器主机名")
    parser.add_argument(
        "--path-segments",
        nargs="+",
        metavar="SEG",
        help="多段路径（如：test agent nanobot）。生成单条 DID，直接写入 --output-dir。",
    )
    parser.add_argument(
        "--names",
        nargs="+",
        metavar="NAME",
        help="遗留批量：每个 name 一条单段 DID，输出到 --output-dir/<name>/。",
    )
    parser.add_argument("--output-dir", default="./did_output", help="输出目录（多段路径模式直接写入此目录）")
    parser.add_argument(
        "--type",
        dest="node_type",
        choices=["agent", "tool", "user"],
        default="agent",
        help="节点身份角色（默认 agent）",
    )

    args = parser.parse_args()

    if args.path_segments and args.names:
        parser.error("--path-segments 与 --names 互斥，请二选一")
    if not args.path_segments and not args.names:
        parser.error("需要 --path-segments（多段路径）或 --names（批量单段）之一")

    output_dir = Path(args.output_dir).expanduser().resolve()
    print(f"生成 DID 文档至: {output_dir}\n")

    if args.path_segments:
        did_id = generate_one(args.hostname, args.path_segments, args.node_type, output_dir)
        print(f"  ✓ {did_id}")
        print(f"\n共生成 1 个 DID（path = {'/'.join(args.path_segments)}）。")
    else:
        for name in args.names:
            did_id = generate_one(args.hostname, [name], args.node_type, output_dir / name)
            print(f"  ✓ {name}: {did_id}")
        print(f"\n共生成 {len(args.names)} 个 DID。")

    print("\n记得把 did.json 中的 id 回填到对应 config.json 的 did 字段。")


if __name__ == "__main__":
    main()
