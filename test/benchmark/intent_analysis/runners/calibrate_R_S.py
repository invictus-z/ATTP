"""R_S 标定（横向触发阈值）：train_R_S（慢投毒+boundary触发）+ 干净，R_T 作输入，扫描 R_S。

R_S 的真实含义：保证纵向 R_T 检不出的慢投毒（sub-R_T 累积）全部送进横向分析。
  - 慢投毒/边界触发场景：每会话 sub-R_T 跳累积 F=Σs³，应 F>R_S（送横向）→ recall 最大化
  - 干净场景：F 应 <R_S（不误送横向）→ FPR 最小化
R_S 独立于 R_T（R_T 由 calibrate_R_T 在 train_R_T 标定后传入 --r-t）。

前提：train_R_S + 干净场景的 {sid}_llm.db 已生成。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent            # intent_analysis/runners
BENCH_ROOT = HERE.parent.parent                     # test/benchmark
PROJECT_ROOT = BENCH_ROOT.parent.parent             # ATTP repo root
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(BENCH_ROOT))

from intent_analysis.runners import evaluate  # noqa: E402


def scenario_max_F(ideal: dict, hops: list, r_t: float) -> float:
    """该场景恶意 DID 的最大累积 F=Σ(sub-R_T 跳 s³)。
    sub-R_T 跳（s≤R_T）才计入（轴职责分离：R_T 抓单跳恶，F 抓 sub-R_T 累积）。"""
    mal_dids = set(ideal["meta"]["malicious_dids"])
    did_F = defaultdict(float)
    for tid, sess, did, s in hops:
        if s <= r_t:
            did_F[did] += s ** 3
    if mal_dids:
        return max((did_F.get(d, 0) for d in mal_dids), default=0.0)
    return max(did_F.values(), default=0.0)


def load_split_hops(results_dir: Path, split: str, category_filter: str = ""):
    out = []
    for sid, dbp in evaluate.all_scenario_files():
        ideal = evaluate.load_ideal(dbp)
        if ideal["meta"].get("split") != split:
            continue
        if category_filter and ideal["meta"].get("category") != category_filter:
            continue
        db = results_dir / f"{sid}_llm.db"
        if not db.exists():
            continue
        c = sqlite3.connect(str(db), timeout=2); c.row_factory = sqlite3.Row
        # 跳过未跑完的空库（无 vertical_hop_scores 表或空）
        tabs = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        if "vertical_hop_scores" not in tabs:
            c.close(); continue
        hops = [(r["trace_id"], r["session_id"], r["sender_did"], r["score"])
                for r in c.execute(
                    "SELECT trace_id,session_id,sender_did,score FROM vertical_hop_scores")]
        c.close()
        if not hops:
            continue
        out.append((sid, ideal, hops))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--r-t", type=float, required=True, help="已标定的 R_T（来自 calibrate_R_T）")
    ap.add_argument("--provider-dir", default="")
    ap.add_argument("--results-root", default=str(evaluate.DEFAULT_RESULTS_ROOT))
    ap.add_argument("--rs-min", type=float, default=5.0)
    ap.add_argument("--rs-max", type=float, default=250.0)
    ap.add_argument("--rs-step", type=float, default=5.0)
    ap.add_argument("--R0", type=float, default=0.95, help="慢投毒送横向 recall 硬约束")
    args = ap.parse_args()

    r_t = args.r_t
    results_dir = evaluate.resolve_results_dir(
        Path(args.results_root), model=args.model, provider_dir=args.provider_dir or None)
    # 应送横向：train_R_S（慢投毒 + boundary 触发）
    slow = load_split_hops(results_dir, "train_R_S")
    # 不应误送：train_R_T 的干净场景（c*）
    clean = load_split_hops(results_dir, "train_R_T", category_filter="clean")

    slow_F = [scenario_max_F(i, h, r_t) for _, i, h in slow]
    clean_F = [scenario_max_F(i, h, r_t) for _, i, h in clean]

    print("=" * 85)
    print(f"  R_S 标定（慢投毒送横向）  R_T={r_t}  model={args.model}  R0={args.R0}")
    print("=" * 85)
    print(f"\n  应送横向(train_R_S) {len(slow)} 场景: F min={min(slow_F):.1f} "
          f"max={max(slow_F):.1f} mean={sum(slow_F)/len(slow_F):.1f}")
    if clean_F:
        print(f"  不应误送(干净) {len(clean_F)} 场景: F min={min(clean_F):.1f} "
              f"max={max(clean_F):.1f} mean={sum(clean_F)/len(clean_F):.1f}")

    n_steps = int(round((args.rs_max - args.rs_min) / args.rs_step)) + 1
    r_s_list = [round(args.rs_min + i * args.rs_step, 2) for i in range(n_steps)]
    # R_S 职责=补纵向漏的慢投毒：F>0（有 sub-R_T 累积）才需横向；F=0=纵向已抓(高分)不计入分母
    need_horiz_F = [F for F in slow_F if F > 0]
    n_vert_caught = len(slow_F) - len(need_horiz_F)
    print(f"\n  需横向补(纵向漏, F>0): {len(need_horiz_F)}/{len(slow_F)}；纵向已抓(F=0): {n_vert_caught}")
    print(f"\n{'r_s':>7} | {'慢投毒送横向R':>13} {'干净误送FPR':>12}")
    print("-" * 45)
    rows = []
    for r_s in r_s_list:
        trig = sum(1 for F in need_horiz_F if F > r_s) / max(len(need_horiz_F), 1)
        fpr = sum(1 for F in clean_F if F > r_s) / max(len(clean_F), 1)
        flag = "  <-- 推荐区间" if (trig >= args.R0 and fpr <= 0.1) else ""
        print(f"{r_s:>7} | {trig:>13.3f} {fpr:>12.3f}{flag}")
        rows.append({"r_s": r_s, "slow_recall": trig, "clean_fpr": fpr})

    feas = [r for r in rows if r["slow_recall"] >= args.R0]
    if feas:
        best = min(feas, key=lambda r: r["clean_fpr"])
        print(f"\n>>> 推荐 R_S = {best['r_s']}  (慢投毒R={best['slow_recall']:.3f}>=R0={args.R0}, "
              f"干净FPR={best['clean_fpr']:.3f})")
    else:
        best = max(rows, key=lambda r: r["slow_recall"])
        print(f"\n⚠ R0={args.R0} 不可满足！最高慢投毒R={best['slow_recall']:.3f} (r_s={best['r_s']})")
        print("  → 检查慢投毒 F 是否足够大，或 R_T 过高导致 sub-R_T 跳过少")

    out = results_dir / "calibrate_R_S.json"
    json.dump({"model": args.model, "r_t": r_t, "R0": args.R0, "rows": rows,
               "recommended": best}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f">>> 报告: {out}")


if __name__ == "__main__":
    main()
