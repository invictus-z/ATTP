"""confirm（H-Reasoner 横向确认）判准率评估：直接读 {sid}_llm.db 的横向报告。

验证 confirm 能否消化 R_S 触发的误送（R_S 宁滥勿缺送横向，confirm 精准过滤）。

双口径：
  - raw（所有恶意DID）：含被纵向 R_T 单跳抓的——confirm 对它们判 clean 是职责分离的正常表现
  - duty（confirm 本职）：排除 vert_hit（max_score>R_T，已被纵向抓）的恶意 DID，
    只算"纵向漏掉、该 confirm 补抓"的累积型攻击 + 干净 DID

干净 DID（clean_coexist_dids）：confirm 应判 clean（TN）；suspicious 算谨慎提醒（TN）；
FP 只计明确 malicious。

用法:
  python test/benchmark/intent_analysis/confirm_eval.py --model chatgpt
  python test/benchmark/intent_analysis/confirm_eval.py --model chatgpt --r-t 7.0
"""
from __future__ import annotations

import argparse
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


def did_max_score(db_path: Path) -> dict:
    """per-DID 最大单跳分数（判 vert_hit）。"""
    if not db_path.exists():
        return {}
    try:
        c = sqlite3.connect(str(db_path), timeout=2)
        out = {}
        for did, mx in c.execute(
            "SELECT sender_did, MAX(score) FROM vertical_hop_scores GROUP BY sender_did"):
            out[did] = mx or 0.0
        c.close()
        return out
    except sqlite3.Error:
        return {}


def _tally(cm: dict, truth_mal: bool, confirmed: bool, pred_malicious: bool) -> None:
    if truth_mal and confirmed:
        cm["tp"] += 1
    elif truth_mal and not confirmed:
        cm["fn"] += 1
    elif not truth_mal and pred_malicious:
        cm["fp"] += 1
    else:
        cm["tn"] += 1


def metrics(cm: dict) -> dict:
    tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return {"P": p, "R": r, "F1": f1, "FPR": fpr, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def evaluate_split(results_dir: Path, split: str, r_t: float):
    cm_raw = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}   # 所有恶意DID
    cm_duty = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}  # 排除 vert_hit（confirm 本职）
    details_fn = []
    n_scn = 0
    for sid, dbp in evaluate.all_scenario_files():
        ideal = evaluate.load_ideal(dbp)
        if ideal["meta"].get("split") != split:
            continue
        res = evaluate.load_llm_result_from_db(sid, results_dir)
        if res.error:
            continue
        n_scn += 1
        mal = set(ideal["meta"]["malicious_dids"])
        coexist = set(ideal["meta"]["clean_coexist_dids"])
        dmax = did_max_score(results_dir / f"{sid}_llm.db")
        for did in mal | coexist:
            truth_mal = did in mal
            overall = res.horiz_overall.get(did, "clean")
            confirmed = did in res.horiz_confirmed        # loose: 含 suspicious
            pred_malicious = (overall == "malicious")     # strict
            vert_hit = dmax.get(did, 0.0) > r_t           # 已被纵向 R_T 单跳抓
            _tally(cm_raw, truth_mal, confirmed, pred_malicious)
            # duty: vert_hit 的恶意DID 不算 confirm 责任；clean 照算
            if not (truth_mal and vert_hit):
                _tally(cm_duty, truth_mal, confirmed, pred_malicious)
            if truth_mal and not confirmed:
                details_fn.append((sid, did.split(":")[-1],
                                   "vert" if vert_hit else "duty", overall))
    return cm_raw, cm_duty, details_fn, n_scn


def main():
    ap = argparse.ArgumentParser(description="confirm 横向确认判准率（双口径）")
    ap.add_argument("--model", required=True)
    ap.add_argument("--provider-dir", default="")
    ap.add_argument("--r-t", type=float, default=7.0, help="vert_hit 判定阈值（来自 calibrate_R_T）")
    ap.add_argument("--splits", default="train_R_S,test,train_R_T")  # train_horiz 已并入 test
    ap.add_argument("--results-root", default=str(evaluate.DEFAULT_RESULTS_ROOT))
    args = ap.parse_args()

    results_dir = evaluate.resolve_results_dir(
        Path(args.results_root), model=args.model, provider_dir=args.provider_dir or None)
    splits = args.splits.split(",")

    print("=" * 84)
    print(f"  confirm(H-Reasoner) 判准率  model={args.model}  R_T={args.r_t}  splits={splits}")
    print("  raw=所有恶意DID;  duty=排除vert_hit(纵向已抓)→confirm本职(补纵轴漏)")
    print("=" * 84)

    all_raw = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    all_duty = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for sp in splits:
        cm_r, cm_d, fns, n_scn = evaluate_split(results_dir, sp, args.r_t)
        mr, md = metrics(cm_r), metrics(cm_d)
        for k in all_raw:
            all_raw[k] += cm_r[k]; all_duty[k] += cm_d[k]
        print(f"\n[{sp}] 场景={n_scn}")
        print(f"  raw  DID={sum(cm_r.values()):>3}  P={mr['P']:.3f} R={mr['R']:.3f} "
              f"F1={mr['F1']:.3f} FPR={mr['FPR']:.3f}  TP/FP/FN/TN="
              f"{mr['tp']}/{mr['fp']}/{mr['fn']}/{mr['tn']}")
        print(f"  duty DID={sum(cm_d.values()):>3}  P={md['P']:.3f} R={md['R']:.3f} "
              f"F1={md['F1']:.3f} FPR={md['FPR']:.3f}  TP/FP/FN/TN="
              f"{md['tp']}/{md['fp']}/{md['fn']}/{md['tn']}")
        for sid, did, kind, overall in fns:
            print(f"    FN[{kind}] {sid} {did}: confirm={overall}")

    mr, md = metrics(all_raw), metrics(all_duty)
    print("\n" + "-" * 84)
    print(f"[合计 raw ] DID={sum(all_raw.values())}  P={mr['P']:.3f} R={mr['R']:.3f} "
          f"F1={mr['F1']:.3f} FPR={mr['FPR']:.3f}  TP/FP/FN/TN={mr['tp']}/{mr['fp']}/{mr['fn']}/{mr['tn']}")
    print(f"[合计 duty] DID={sum(all_duty.values())}  P={md['P']:.3f} R={md['R']:.3f} "
          f"F1={md['F1']:.3f} FPR={md['FPR']:.3f}  TP/FP/FN/TN={md['tp']}/{md['fp']}/{md['fn']}/{md['tn']}")

    out = results_dir / "confirm_eval.json"
    json.dump({"model": args.model, "r_t": args.r_t, "splits": splits,
               "raw": mr, "duty": md}, open(out, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f">>> 报告: {out}")


if __name__ == "__main__":
    main()
