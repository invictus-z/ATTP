"""ATTP 工具节点 ad.json 生成脚本

为 ATTP 工具节点生成服务描述文件（ad.json），供 Agent 发现和连接。

用法：
    python scripts/tool_ad_creator.py \
        --did did:wba:tool.local:search-service \
        --name search-service \
        --endpoint http://localhost:9000/attp \
        --tool search "搜索知识库" \
        --tool translate "翻译文本" \
        --output ad.json
"""

import argparse
import json
import sys
from pathlib import Path


def build_tool_schema(name: str, description: str) -> dict:
    """构建单个 MCP 工具描述。"""
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="为 ATTP 工具节点生成 ad.json 服务描述文件",
    )
    parser.add_argument("--did", required=True, help="工具节点的 DID 标识")
    parser.add_argument("--name", required=True, help="工具节点名称")
    parser.add_argument("--description", default="", help="工具节点描述")
    parser.add_argument("--endpoint", required=True, help="ATTP 端点 URL")
    parser.add_argument("--public-key-endpoint", default="", help="公钥端点 URL")
    parser.add_argument(
        "--tool", nargs=2, action="append", metavar=("NAME", "DESC"),
        help="注册一个工具（可多次使用）",
    )
    parser.add_argument("--tools-json", default=None, help="从 JSON 文件读取工具定义")
    parser.add_argument("--output", default="ad.json", help="输出文件路径")

    args = parser.parse_args()

    if args.tools_json:
        tools_path = Path(args.tools_json)
        tools = json.loads(tools_path.read_text(encoding="utf-8"))
    elif args.tool:
        tools = [build_tool_schema(n, d) for n, d in args.tool]
    else:
        tools = []

    ad = {
        "type": "attp-tool-node",
        "version": "0.1.0",
        "identifier": args.did,
        "name": args.name,
        "description": args.description,
        "attp_endpoint": args.endpoint,
        "public_key_endpoint": args.public_key_endpoint,
        "mcp_tools": tools,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(ad, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"✓ ad.json 已生成: {output_path}")
    print(f"  DID: {args.did}")
    print(f"  名称: {args.name}")
    print(f"  端点: {args.endpoint}")
    print(f"  工具数: {len(tools)}")
    for tool in tools:
        print(f"    - {tool.get('name', '?')}: {tool.get('description', '')}")


if __name__ == "__main__":
    main()