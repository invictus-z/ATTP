"""测试协议节点 LLM 连通性 & 余额是否充足。

用法:
    python scripts/test_llm.py                        # 使用默认配置
    python scripts/test_llm.py -n 10                  # 测试 10 次
    python scripts/test_llm.py -k sk-xxx -u https://xxx/v1 -m model-name
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from openai import AsyncOpenAI

# 尝试从协议节点配置文件加载默认值
DEFAULT_CONFIG_PATH = Path.home() / ".attp" / "agent" / "protocol_node" / "config.json"


def load_defaults() -> dict:
    if DEFAULT_CONFIG_PATH.exists():
        cfg = json.loads(DEFAULT_CONFIG_PATH.read_text("utf-8"))
        analysis = cfg.get("analysis", {})
        return {
            "api_key": analysis.get("apiKey", "sk-tndjmdbokroduydqwluzznlryzypkzitbiikqbepgvatacej"),
            "base_url": analysis.get("baseUrl", "https://api.siliconflow.cn/v1"),
            "model": analysis.get("model", "deepseek-ai/DeepSeek-V3.2"),
        }
    return {}


PROMPTS = [
    "请用一句话描述什么是污点分析，以JSON格式输出，key为\"answer\"。",
    "请用一句话描述什么是DID去中心化身份，以JSON格式输出，key为\"answer\"。",
    "请用一句话描述什么是多Agent系统，以JSON格式输出，key为\"answer\"。",
    "请用一句话描述什么是溯源链，以JSON格式输出，key为\"answer\"。",
    "请用一句话描述什么是零知识证明，以JSON格式输出，key为\"answer\"。",
]


async def run_test(api_key: str, base_url: str, model: str, count: int):
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    print(f"端点: {base_url}")
    print(f"模型: {model}")
    print(f"测试次数: {count}")
    print("-" * 60)

    ok = 0
    fail = 0
    total_tokens = 0

    for i in range(1, count + 1):
        prompt = PROMPTS[(i - 1) % len(PROMPTS)]
        t0 = time.perf_counter()
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是一个安全审计助手，只输出 JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            elapsed = time.perf_counter() - t0
            tokens = resp.usage.total_tokens
            total_tokens += tokens
            ok += 1
            content = resp.choices[0].message.content[:50]
            print(f"  [{i}/{count}] OK  | {elapsed:.1f}s | tokens={tokens:>4} | {content}")
        except Exception as e:
            elapsed = time.perf_counter() - t0
            fail += 1
            print(f"  [{i}/{count}] FAIL | {elapsed:.1f}s | {type(e).__name__}: {e}")

    print("-" * 60)
    print(f"结果: {ok} 成功, {fail} 失败, 共消耗 {total_tokens} tokens")
    if fail == count:
        print(">>> 所有请求失败，请检查 API Key 和余额。")


def main():
    defaults = load_defaults()

    parser = argparse.ArgumentParser(description="测试协议节点 LLM 连通性")
    parser.add_argument("-k", "--api-key", default=defaults.get("api_key", ""), help="API Key")
    parser.add_argument("-u", "--base-url", default=defaults.get("base_url", ""), help="API 端点")
    parser.add_argument("-m", "--model", default=defaults.get("model", ""), help="模型名称")
    parser.add_argument("-n", "--count", type=int, default=5, help="测试次数 (默认 5)")
    args = parser.parse_args()

    if not args.api_key:
        print("错误: 未提供 API Key，请通过 -k 参数或配置文件提供。")
        sys.exit(1)

    asyncio.run(run_test(args.api_key, args.base_url, args.model, args.count))


if __name__ == "__main__":
    main()
