"""大模型审计开销测量

在样本场景上真实运行谛听 Cross-Lock 审计（复用 evaluate.run_scenario_llm），
仅在外层包一个 InstrumentedClient 拦截每次 chat.completions.create，按 system
message 把调用分类为 intent / vertical / horizontal，记录 token 用量与端到端延迟。

产出：
  - data/results/perf_audit_overhead.json   原始 + 汇总
  - stdout                                  可读汇总表

凭证读取顺序：data/perf_config.local.json（gitignore）→ 环境变量。
运行：
  cd e:/work/ATTP
  python test/benchmark/intent_analysis/perf_audit_overhead.py --concurrency 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

CONFIG_PATH = HERE.parent / "data" / "perf_config.local.json"
RESULTS_DIR = evaluate.DEFAULT_RESULTS_ROOT / "perf_run"

# 代表性样本：4 纵向 + 3 横向 + 2 干净 + 1 边界，覆盖 intent/vertical/horizontal 三类调用
DEFAULT_SAMPLE = ["v01", "v08", "v15", "v22", "h03", "h10", "h16", "c03", "c08", "b04"]

# DeepSeek-V3.2 列表价（元 / 1M tokens），仅用于费用估算，结果中会显式标注为估算
PRICE_INPUT_PER_M = 1.0   # 输入（cache miss 混合）
PRICE_OUTPUT_PER_M = 4.0  # 输出


def load_perf_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {
        "api_key": os.environ.get("BLTCY_API_KEY", ""),
        "base_url": os.environ.get("BLTCY_BASE_URL", "https://api.siliconflow.cn/v1"),
        "model": os.environ.get("ATTP_BENCHMARK_MODEL", "deepseek-ai/DeepSeek-V3.2"),
    }


# ── 埋点客户端 ──────────────────────────────────────────────────────────────

def _classify(messages: list[dict]) -> str:
    sys_msg = ""
    if messages and messages[0].get("role") == "system":
        sys_msg = messages[0].get("content", "") or ""
    if "安全审计助手" in sys_msg:        # 纵向意图提取
        return "intent"
    if "跨Session" in sys_msg or "跨 Session" in sys_msg:  # 横向分析
        return "horizontal"
    if "审计员" in sys_msg:              # 纵向分析
        return "vertical"
    return "unknown"


class _Completions:
    def __init__(self, real, log: list):
        self._real = real
        self._log = log

    async def create(self, **kwargs):
        kind = _classify(kwargs.get("messages", []))
        t0 = time.perf_counter()
        try:
            resp = await self._real.create(**kwargs)
        except Exception as e:
            self._log.append({"kind": kind, "latency": time.perf_counter() - t0,
                              "error": f"{type(e).__name__}: {e}",
                              "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
            raise
        dt = time.perf_counter() - t0
        usage = getattr(resp, "usage", None)
        self._log.append({
            "kind": kind,
            "latency": dt,
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            "model": kwargs.get("model"),
        })
        return resp


class _Chat:
    def __init__(self, real_chat, log):
        self.completions = _Completions(real_chat.completions, log)


class InstrumentedClient:
    """伪装成 AsyncOpenAI：仅拦截 chat.completions.create，其余透传。"""

    def __init__(self, real: AsyncOpenAI, log: list):
        self._real = real
        self.chat = _Chat(real.chat, log)


# ── 统计 ────────────────────────────────────────────────────────────────────

def _pct(sorted_data: list[float], p: float) -> float:
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0}
    lats = sorted(r["latency"] for r in rows)
    pts = [r["prompt_tokens"] for r in rows]
    cts = [r["completion_tokens"] for r in rows]
    tts = [r["total_tokens"] for r in rows]
    return {
        "n": len(rows),
        "latency_mean_s": round(statistics.mean(lats), 3),
        "latency_median_s": round(statistics.median(lats), 3),
        "latency_p95_s": round(_pct(lats, 0.95), 3),
        "latency_max_s": round(max(lats), 3),
        "prompt_tokens_mean": round(statistics.mean(pts), 1),
        "completion_tokens_mean": round(statistics.mean(cts), 1),
        "total_tokens_mean": round(statistics.mean(tts), 1),
        "total_tokens_sum": sum(tts),
        "prompt_tokens_sum": sum(pts),
        "completion_tokens_sum": sum(cts),
    }


# ── 主流程 ──────────────────────────────────────────────────────────────────

async def run(sample: list[str], concurrency: int) -> dict:
    cfg = load_perf_config()
    if not cfg.get("api_key"):
        raise SystemExit(f"未找到 API key：请在 {CONFIG_PATH} 配置 api_key，或设置 BLTCY_API_KEY")

    files = dict(evaluate.all_scenario_files())
    sample_files = [(sid, files[sid]) for sid in sample if sid in files]
    missing = [s for s in sample if s not in files]
    if missing:
        print(f"  [warn] 样本中缺失的场景（已跳过）: {missing}")
    if not sample_files:
        raise SystemExit("无可用场景，先运行 generate_all.py 生成场景 DB")

    real_client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    llm_config = {"api_key": cfg["api_key"], "base_url": cfg["base_url"], "model": cfg["model"]}
    log: list = []
    client = InstrumentedClient(real_client, log)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)

    # 统计样本总会话数（用于"每会话调用数"口径）
    total_sessions = 0
    for _, dbp in sample_files:
        ideal = evaluate.load_ideal(dbp)
        total_sessions += len(ideal["session_order"])

    print(f"  模型: {cfg['model']} @ {cfg['base_url']}")
    print(f"  样本: {len(sample_files)} 场景 / {total_sessions} 会话, concurrency={concurrency}")
    t0 = time.perf_counter()
    tasks = [evaluate.run_scenario_llm(sid, dbp, llm_config, client, sem, RESULTS_DIR)
             for sid, dbp in sample_files]
    await asyncio.gather(*tasks, return_exceptions=True)
    wall = time.perf_counter() - t0

    ok = [r for r in log if not r.get("error")]
    errs = [r for r in log if r.get("error")]
    by_kind = {k: [r for r in ok if r["kind"] == k] for k in ("intent", "vertical", "horizontal", "unknown")}

    n_scenarios = len(sample_files)
    overall = _stats(ok)
    summary = {
        "model": cfg["model"],
        "base_url": cfg["base_url"],
        "n_scenarios": n_scenarios,
        "total_sessions": total_sessions,
        "wall_time_s": round(wall, 1),
        "total_calls": len(ok),
        "failed_calls": len(errs),
        "calls_per_scenario": round(len(ok) / n_scenarios, 2),
        "calls_per_session": round(len(ok) / total_sessions, 2) if total_sessions else 0,
        "overall": overall,
        "by_kind": {k: _stats(v) for k, v in by_kind.items()},
    }
    # 费用估算（元）
    pin = overall.get("prompt_tokens_sum", 0)
    pout = overall.get("completion_tokens_sum", 0)
    summary["cost_estimate_cny"] = round(pin / 1_000_000 * PRICE_INPUT_PER_M
                                         + pout / 1_000_000 * PRICE_OUTPUT_PER_M, 4)
    summary["cost_assumption"] = (f"DeepSeek-V3.2 列表价估算："
                                  f"输入 {PRICE_INPUT_PER_M} 元/M、输出 {PRICE_OUTPUT_PER_M} 元/M")
    summary["per_scenario_cost_cny"] = round(summary["cost_estimate_cny"] / n_scenarios, 4)
    if errs:
        summary["errors"] = errs[:10]

    out = RESULTS_DIR.parent / "perf_audit_overhead.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 可读汇总 ──
    print("\n" + "=" * 70)
    print("  大模型审计开销测量结果")
    print("=" * 70)
    print(f"  场景 {n_scenarios} / 会话 {total_sessions} / 总调用 {len(ok)}"
          f"（失败 {len(errs)}）/ 墙钟 {wall:.1f}s")
    print(f"  每场景调用: {summary['calls_per_scenario']}  每会话调用: {summary['calls_per_session']}")
    print(f"  Token 合计: 输入 {pin} / 输出 {pout} / 合计 {pin+pout}")
    print(f"  费用估算: {summary['cost_estimate_cny']} 元（{summary['cost_assumption']}）")
    print(f"  每场景费用: {summary['per_scenario_cost_cny']} 元")
    print("\n  分类别（mean / median / p95 延迟s ; 平均 输入→输出 token）:")
    for k in ("intent", "vertical", "horizontal"):
        s = summary["by_kind"][k]
        if not s.get("n"):
            continue
        print(f"    {k:<10} n={s['n']:<3} lat mean/med/p95 = "
              f"{s['latency_mean_s']}/{s['latency_median_s']}/{s['latency_p95_s']}s ; "
              f"tok {s['prompt_tokens_mean']:.0f}→{s['completion_tokens_mean']:.0f}")
    o = overall
    print(f"\n  总体每次调用: 延迟 mean/med/p95 = {o['latency_mean_s']}/{o['latency_median_s']}/{o['latency_p95_s']}s ; "
          f"平均 token {o['prompt_tokens_mean']:.0f}+{o['completion_tokens_mean']:.0f}={o['total_tokens_mean']:.0f}")
    print(f"\n>>> 已保存: {out}")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=",".join(DEFAULT_SAMPLE),
                    help="逗号分隔的场景 ID 列表")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    sample = [s.strip() for s in args.sample.split(",") if s.strip()]
    asyncio.run(run(sample, args.concurrency))


if __name__ == "__main__":
    main()
