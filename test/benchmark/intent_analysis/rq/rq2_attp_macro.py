"""RQ2-ATTP Macro-F1：从现有 gemini train_R_T 纵向 hop_scores 重算（只读，零新 LLM）。

Macro-F1 = {偏离, 干净} 二类宏平均。
truth: ideal_s > TAU_DEV(1.0)；pred: actual_score > R_T(7.0)。
口径同 evaluate.py 行为级，仅把 micro F1 换成 macro。

注意：train_R_T 是 R_T 的标定集 → 绝对值偏乐观（in-sample）；但与 Direct Judge 同集配对比较有效。
"""
from __future__ import annotations

import asyncio
import sqlite3

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402


def compute():
    tp = fp = fn = tn = 0
    n_scn = n_hops = 0
    per_scn_f1 = []
    for sid, scen, _ in c.scen_files("train_R_T"):
        ideal = c.load_ideal(scen)
        meta = ideal["meta"]
        hop_ideals = {int(k): v for k, v in meta["hop_ideals"].items()}
        rdb = c.results_db(sid)
        if not rdb.exists():
            continue
        conn = sqlite3.connect(str(rdb))
        actual = {r[0]: r[1] for r in conn.execute(
            "SELECT trace_id, score FROM vertical_hop_scores")}
        conn.close()
        n_scn += 1
        s_tp = s_fp = s_fn = s_tn = 0
        for tid in evaluate.action_trace_ids(ideal):
            truth = tid in hop_ideals and hop_ideals[tid]["s"] > c.TAU_DEV
            pred = actual.get(tid, 0.0) > c.R_T
            n_hops += 1
            if truth and pred: s_tp += 1; tp += 1
            elif truth and not pred: s_fn += 1; fn += 1
            elif not truth and pred: s_fp += 1; fp += 1
            else: s_tn += 1; tn += 1
        per_scn_f1.append(c.macro_f1_binary(s_tp, s_fp, s_fn, s_tn))

    macro = c.macro_f1_binary(tp, fp, fn, tn)
    # 单类 F1
    def f1(tp_, fp_, fn_):
        p = tp_/(tp_+fp_) if tp_+fp_ else 0; r = tp_/(tp_+fn_) if tp_+fn_ else 0
        return 2*p*r/(p+r) if p+r else 0
    out = {
        "split": "train_R_T", "model": c.MODEL, "R_T": c.R_T, "TAU_DEV": c.TAU_DEV,
        "n_scenarios": n_scn, "n_hops": n_hops,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "F1_deviation": f1(tp, fp, fn), "F1_clean": f1(tn, fn, fp),
        "macro_f1": macro,
        "mean_per_scenario_macro_f1": sum(per_scn_f1)/len(per_scn_f1) if per_scn_f1 else 0,
    }
    p = c.save_json("rq2_attp_macro.json", out)
    print(f"[ATTP] train_R_T scn={n_scn} hops={n_hops} "
          f"TP/FP/FN/TN={tp}/{fp}/{fn}/{tn}")
    print(f"  F1(偏离)={out['F1_deviation']:.3f}  F1(干净)={out['F1_clean']:.3f}  "
          f"Macro-F1={macro:.3f}  (per-scn mean={out['mean_per_scenario_macro_f1']:.3f})")
    print(f"  -> {p}")
    return out


if __name__ == "__main__":
    from intent_analysis.runners import evaluate  # noqa
    compute()
