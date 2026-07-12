"""按模型批量运行 ATTP 意图追踪基准。

默认会按以下目录落盘：
    data/results/glm/
  data/results/chatgpt/
  data/results/gemini/
  data/results/claude/

可选先跑一次 dry 自检，确认评测逻辑无误后再执行真实 LLM 测试。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(HERE))

import evaluate


DEFAULT_MODEL_MATRIX = [
    ("chatgpt", "gpt-5.4"),
    ("claude", "claude-sonnet-4-6"),
    ("gemini", "gemini-3-pro-preview"),
    ("glm", "glm-5"),
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="", help="逗号分隔的 sid 列表，如 v01,h01,c08；空=全部")
    ap.add_argument("--concurrency", type=int, default=8, help="每个模型的并发场景数")
    ap.add_argument("--model-concurrency", type=int, default=4, help="同时并行运行的模型数")
    ap.add_argument("--results-root", default=str(evaluate.DEFAULT_RESULTS_ROOT), help="结果根目录")
    ap.add_argument("--base-url", default="", help="API base_url；默认读取环境变量或配置文件")
    ap.add_argument("--api-key", default="", help="API key；默认读取环境变量或配置文件")
    ap.add_argument("--skip-dry", action="store_true", help="跳过 dry 自检")
    ap.add_argument("--chatgpt-model", default="gpt-5.4", help="chatgpt 目录对应模型")
    ap.add_argument("--claude-model", default="claude-sonnet-4-6", help="claude 目录对应模型")
    ap.add_argument("--gemini-model", default="gemini-3-pro-preview", help="gemini 目录对应模型")
    ap.add_argument("--glm-model", default="glm-5", help="glm 目录对应模型")
    return ap.parse_args()


async def run_matrix(args: argparse.Namespace) -> None:
    scenario_filter = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    results_root = Path(args.results_root)
    llm_base_url = args.base_url or os.environ.get("BLTCY_BASE_URL", "")
    llm_api_key = args.api_key or os.environ.get("BLTCY_API_KEY", "")

    model_matrix = [
        ("chatgpt", args.chatgpt_model),
        ("claude", args.claude_model),
        ("gemini", args.gemini_model),
        ("glm", args.glm_model),
    ]

    async def run_one_model(provider_dir: str, model: str) -> None:
        llm_config = evaluate.load_llm_config(model, llm_base_url, llm_api_key)
        if not llm_config["api_key"]:
            raise RuntimeError("缺少 API key：请通过 --api-key 或 BLTCY_API_KEY 提供")
        print("=" * 80)
        print(f"  Running {provider_dir} -> {model}")
        print("=" * 80)
        await evaluate.run_llm_mode(
            scenario_filter,
            concurrency=args.concurrency,
            llm_config=llm_config,
            results_root=results_root,
            provider_dir=provider_dir,
        )

    if not args.skip_dry:
        print("=" * 80)
        print("  Dry self-check")
        print("=" * 80)
        evaluate.run_dry_mode(scenario_filter, results_root=results_root)

    model_sem = asyncio.Semaphore(max(1, args.model_concurrency))

    async def guarded_run(provider_dir: str, model: str) -> None:
        async with model_sem:
            await run_one_model(provider_dir, model)

    tasks = [guarded_run(provider_dir, model) for provider_dir, model in model_matrix]
    await asyncio.gather(*tasks)


def main() -> None:
    args = parse_args()
    asyncio.run(run_matrix(args))


if __name__ == "__main__":
    main()