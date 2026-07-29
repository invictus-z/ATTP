"""R_T 标定（行为级偏离阈值）：只用 train_R_T split（v*+c*），扫描 R_T 优化行为级 F1。

R_T 独立于 R_S —— R_S 由 calibrate_R_S 在 train_R_S（慢投毒）上独立标定。
本脚本只评行为级（单跳偏离判定），不涉及横向触发。

前提：train_R_T 的 {sid}_llm.db 已生成（evaluate --mode llm）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # intent_analysis/runners
BENCH_ROOT = HERE.parent.parent                     # test/benchmark
PROJECT_ROOT = BENCH_ROOT.parent.parent             # ATTP repo root
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(BENCH_ROOT))

from intent_analysis.runners import evaluate  # noqa: E402


def files_in_split(results_dir: Path, split: str):
    out = []
    for sid, dbp in evaluate.all_scenario_files():
        ideal = evaluate.load_ideal(dbp)
        if ideal["meta"].get("split") != split:
            continue
        res = evaluate.load_llm_result_from_db(sid, results_dir)
        if res.error:
            continue
        out.append((sid, ideal, res))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--provider-dir", default="")
    ap.add_argument("--results-root", default=str(evaluate.DEFAULT_RESULTS_ROOT))
    ap.add_argument("--r-min", type=float, default=4.0)
    ap.add_argument("--r-max", type=float, default=9.5)
    ap.add_argument("--r-step", type=float, default=0.5)
    ap.add_argument("--target", default="f1", choices=["f1", "recall_at_fpr"],
                    help="f1=行为级F1最大; recall_at_fpr=FPR≤cap下recall最大")
    ap.add_argument("--fpr-cap", type=float, default=0.05)
    args = ap.parse_args()

    n_steps = int(round((args.r_max - args.r_min) / args.r_step)) + 1
    r_t_list = [round(args.r_min + i * args.r_step, 2) for i in range(n_steps)]
    results_dir = evaluate.resolve_results_dir(
        Path(args.results_root), model=args.model, provider_dir=args.provider_dir or None)
    loaded = files_in_split(results_dir, "train_R_T")

    print("=" * 80)
    print(f"  R_T 标定（行为级偏离）  train_R_T={len(loaded)}场景  model={args.model}  target={args.target}")
    print("=" * 80)
    print(f"\n{'r_t':>5} | {'行为P':>6} {'行为R':>6} {'行为F1':>7} {'行为FPR':>8} | {'节点R':>6} | {'MAE':>5}")
    print("-" * 70)
    rows = []
    for r_t in r_t_list:
        ms = {sid: evaluate.evaluate_one(sid, res, ideal, r_t, evaluate.TAU_DEV, "llm")
              for sid, ideal, res in loaded}
        agg = evaluate.aggregate(ms)
        b, n = agg["behavior"], agg["node"]
        print(f"{r_t:>5} | {b['precision']:>6.3f} {b['recall']:>6.3f} {b['f1']:>7.3f} "
              f"{b['fpr']:>8.3f} | {n['recall']:>6.3f} | {agg['score_mae']:>5.3f}")
        rows.append({"r_t": r_t, **agg})

    if args.target == "f1":
        best = max(rows, key=lambda r: r["behavior"]["f1"])
    else:
        feas = [r for r in rows if r["behavior"]["fpr"] <= args.fpr_cap]
        best = (max(feas, key=lambda r: r["behavior"]["recall"]) if feas
                else max(rows, key=lambda r: r["behavior"]["recall"]))
        if not feas:
            print(f"\n⚠ FPR cap={args.fpr_cap} 不可满足，退化为最高 recall")

    print(f"\n>>> 推荐 R_T = {best['r_t']}  (行为F1={best['behavior']['f1']:.3f}  "
          f"R={best['behavior']['recall']:.3f}  FPR={best['behavior']['fpr']:.3f}  MAE={best['score_mae']:.3f})")
    out = results_dir / "calibrate_R_T.json"
    json.dump({"model": args.model, "split": "train_R_T", "target": args.target,
               "rows": rows, "recommended": best}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f">>> 报告: {out}")


if __name__ == "__main__":
    main()
