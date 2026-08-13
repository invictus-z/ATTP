"""离线横向 confirm：各模型 train_R_S 纵向 db → 统一标注 DID 跑横向 confirm。

横向数据集 = train_R_S 的 malicious_dids + clean_coexist_dids（事先标注，所有模型一致）。
不依赖 R_S 触发，对所有标注 DID 手动触发 confirm（保证变量统一）。

复用各模型已生成的纵向 db（vertical_hop_scores），清空旧横向 states/reports，
build_coord attach → trigger_horizontal_async → run_analysis 从 db 读全部跳 → confirm。

输出各模型横向节点级：恶意 DID confirmed(TP/FN) + 干净 DID 误判(FP/TN)。

用法:
  python test/benchmark/intent_analysis/offline_horizontal.py --model gpt-5.4
  python test/benchmark/intent_analysis/offline_horizontal.py --model gpt-5.4 --scenarios h70
"""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # intent_analysis/runners
BENCH_ROOT = HERE.parent.parent                     # test/benchmark
PROJECT_ROOT = BENCH_ROOT.parent.parent             # ATTP repo root
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(BENCH_ROOT))

from intent_analysis.runners import evaluate  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

# v1 恶意节点 confirm 结果（malicious+clean_coexist 跑，仅恶意 DID）。
# 用户要求：恶意节点保留原值，只重测良性节点 FPR。
V1_MAL = {
    "gpt-5.4": (81, 6),
    "claude-sonnet-5": (86, 1),
    "qwen3.7-plus": (82, 5),
    "gemini-3.1-flash-lite": (86, 1),
    "glm-4.6": (83, 4),
    "MiniMax-M3": (75, 10),
}


async def process(sid, dbp, rd, model, client, r_t, sem, benign_only=False):
    ideal = evaluate.load_ideal(dbp)
    if ideal["meta"].get("split") != "train_R_S":
        return None
    db = rd / f"{sid}_llm.db"
    if not evaluate._vertical_done(db, ideal):
        return None
    async with sem:
        db_path = str(db)
        # 清旧横向数据（统一离线重新生成，避免 gpt 等已有横向的 cursor 残留）
        c = sqlite3.connect(db_path)
        c.execute("DELETE FROM horizontal_analysis_states")
        c.execute("DELETE FROM horizontal_analysis_reports")
        c.commit(); c.close()
        # build_coord attach 已存在 db（纵向数据保留）+ trigger
        coord = await evaluate.build_coord(db_path, model, client, r_t)
        meta = ideal["meta"]
        mal = set(meta["malicious_dids"])
        agent_dids = {t.get("node_did", "") for t in ideal["traces"]
                      if ":agent:" in t.get("node_did", "")}
        # benign_only: 只跑良性 agent(coordinator 等)，恶意保留 v1 值不重跑
        dids = sorted(agent_dids - mal) if benign_only else sorted(agent_dids)
        for did in dids:
            async with coord.horizontal._get_lock(did):
                await coord.horizontal.run_analysis(did)
        await coord.shutdown()
        # 读 reports
        c = sqlite3.connect(db_path); c.row_factory = sqlite3.Row
        reports = {}
        for r in c.execute("SELECT did, report_json FROM horizontal_analysis_reports ORDER BY id"):
            rj = json.loads(r["report_json"] or "{}")
            reports[r["did"]] = (rj.get("overall_verdict", "clean"),
                                 (rj.get("verdict", {}) or {}).get("confirmed", False))
        c.close()
        return sid, ideal, reports


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--scenarios", default="")
    ap.add_argument("--r-t", type=float, default=7.0)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--provider-dir", default="",
                    help="结果目录覆盖（glm-4.6 须传 glm-4.6，否则 infer 映射到旧 glm）")
    ap.add_argument("--benign-cap", type=int, default=61,
                    help="良性 coordinator 节点上限（按 sid 取前 N 场景）")
    ap.add_argument("--all-agents", action="store_true",
                    help="跑全部 agent(含恶意)；默认仅良性(恶意用 v1 值)")
    args = ap.parse_args()

    cfg = evaluate.load_llm_config(args.model)
    client = AsyncOpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])
    rd = evaluate.resolve_results_dir(
        Path(evaluate.DEFAULT_RESULTS_ROOT), model=args.model,
        provider_dir=args.provider_dir or None)
    sf = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    sem = asyncio.Semaphore(args.concurrency)
    benign_only = not args.all_agents

    # 选 train_R_S 场景（benign_only 下取前 benign_cap 个测良性 coordinator）
    scn = [(sid, dbp) for sid, dbp in evaluate.all_scenario_files(sf)
           if evaluate.load_ideal(dbp)["meta"].get("split") == "train_R_S"]
    if benign_only:
        scn = scn[: args.benign_cap]

    tasks = [process(sid, dbp, rd, args.model, client, args.r_t, sem, benign_only)
             for sid, dbp in scn]
    results = await asyncio.gather(*tasks)

    # 统计本次跑的节点（benign_only 下全是良性）
    fp = tn = 0
    n_benign = 0
    for r in results:
        if r is None:
            continue
        sid, ideal, reports = r
        mal = set(ideal["meta"]["malicious_dids"])
        for did, (overall, confirmed) in reports.items():
            if did in mal:
                continue  # benign_only 下不会有，兜底
            n_benign += 1
            conf = confirmed or overall in ("malicious", "suspicious")
            if conf:
                fp += 1
            else:
                tn += 1

    if benign_only:
        # 恶意用 v1 原值（不重跑，避免随机性）
        tp, fn = V1_MAL.get(args.model, (0, 0))
        n_mal = tp + fn
    else:
        # all-agents 模式：恶意也从本次算
        tp = fn = n_mal = 0
        for r in results:
            if r is None:
                continue
            sid, ideal, reports = r
            mal = set(ideal["meta"]["malicious_dids"])
            for did, (overall, confirmed) in reports.items():
                if did not in mal:
                    continue
                n_mal += 1
                conf = confirmed or overall in ("malicious", "suspicious")
                if conf:
                    tp += 1
                else:
                    fn += 1

    P = tp / (tp + fp) if tp + fp else 0
    R = tp / (tp + fn) if tp + fn else 0
    F1 = 2 * P * R / (P + R) if P + R else 0
    FPR = fp / (fp + tn) if fp + tn else 0
    mode = "良性only(恶意用v1)" if benign_only else "全agent"
    print(f"{args.model}: [{mode}] 节点(恶意{n_mal}+良性{n_benign}={n_mal+n_benign}) "
          f"TP/FP/FN/TN={tp}/{fp}/{fn}/{tn} P={P:.3f} R={R:.3f} F1={F1:.3f} FPR={FPR:.3f}")


if __name__ == "__main__":
    asyncio.run(main())
