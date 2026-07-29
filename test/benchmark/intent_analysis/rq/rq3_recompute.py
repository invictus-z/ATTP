"""RQ3 最终重算（无 LLM）：横向 confirm taint 为判别分（纵轴在良性 coordinator 上误报，
confirm 负责过滤——故 confirm 输出才是判别量，纵轴各法共享不计入）。

支持 --split train_R_S|test。test 从 data/results/rq/gemini/ 读（rq_test_vertical 产物）。
Vertical-Only 消融内联计算（any hop>R_T），不依赖 rq3_readonly.json。

方法（campaign 节点级）：
  Full-History : 全上下文 confirm taint；calls=N（每 campaign 一次）
  Coreset      : 有界记忆 confirm taint；calls=N（同 calls、更少 token）
  Periodic     : 固定调度、预算匹配 ATTP，按到达轮询漏审（含若干恶意）
  ATTP         : 风险触发 confirm(F>R_S)；漏审低累积恶意（纵轴可补部分）
"""
from __future__ import annotations

import argparse
import json
import sqlite3

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402

SPLIT = "train_R_S"
ROOT = None  # None=GEMINI_RES；test=c.RQ_RES


def _scores_db():
    return c.RQ_RES / ("rq3_scores_test.db" if SPLIT == "test" else "rq3_scores.db")


def _out_name():
    return "rq3_results.json" if SPLIT == "train_R_S" else "rq3_results_test.json"


def recompute():
    db = _scores_db()
    taint = {}
    if db.exists():
        cc = sqlite3.connect(str(db)); cc.row_factory = sqlite3.Row
        for r in cc.execute("SELECT sid,did,method,taint FROM scores"):
            taint[(r["sid"], r["did"], r["method"])] = r["taint"]
        cc.close()
    evp = c.RQ_RES / ("rq3_events_test.json" if SPLIT == "test" else "rq3_events.json")
    if not evp.exists() and SPLIT == "train_R_S":
        evp = c.RQ_RES / "rq3_events_train_R_S.json"
    ev = json.load(open(evp)) if evp.exists() else {"total_events": 0}
    E = ev["total_events"]

    camps = []
    for sid, scen, meta in c.scen_files(SPLIT):
        mal = set(meta["malicious_dids"])
        for did, hs in c.load_did_hops(sid, ROOT).items():
            if ":agent:" not in did:
                continue
            scores = [h["score"] for h in hs]
            camps.append({"sid": sid, "did": did, "mal": did in mal,
                          "F": c.f_accumulation(hs), "max": max(scores) if scores else 0.0,
                          "min_t": min(h["trace_id"] for h in hs),
                          "full": taint.get((sid, did, "full"), 0.0),
                          "coreset": taint.get((sid, did, "coreset"), 0.0)})
    camps.sort(key=lambda x: x["min_t"])
    n = len(camps)
    labels = [1 if x["mal"] else 0 for x in camps]
    P = sum(labels)

    # Periodic 预算匹配：固定轮询漏审（≈固定审计间隔，预算≈ATTP）
    # 漏审比例 ~ ATTP 非触发比例
    attp_trig = sum(1 for x in camps if x["F"] > c.R_S)
    skip_target = max(0, n - attp_trig)
    step = max(2, round(n / max(1, skip_target))) if skip_target else n + 1
    periodic_skip = {i for i in range(n) if i % step == (step - 1)}

    def auprc_rec(sc):
        return {"AUPRC": c.auprc(sc, labels), "Rec@5%FPR": c.recall_at_fpr(sc, labels, 0.05)}

    def with_calls(rec, calls):
        rec["calls"] = calls
        rec["calls_per_1k"] = round(calls / E * 1000, 1) if E else 0
        return rec

    full_sc = [x["full"] for x in camps]
    core_sc = [x["coreset"] for x in camps]
    per_sc = [0.0 if i in periodic_skip else x["full"] for i, x in enumerate(camps)]
    attp_sc = [x["full"] if x["F"] > c.R_S else 0.0 for x in camps]
    # Vertical-Only（内联）：any hop>R_T
    vert_hit = [1 if x["max"] > c.R_T else 0 for x in camps]
    v_tp = sum(1 for x, h in zip(camps, vert_hit) if x["mal"] and h)
    v_fp = sum(1 for x, h in zip(camps, vert_hit) if (not x["mal"]) and h)
    v_fn = P - v_tp; v_tn = (n - P) - v_fp

    res = {
        "model": c.MODEL, "split": SPLIT, "R_T": c.R_T, "R_S": c.R_S, "total_events": E,
        "n_campaigns": n, "n_mal": P, "n_benign": n - P,
        "scoring": "horizontal confirm taint (vertical shared, excluded; confirm filters its FAs)",
        "methods": {
            "Full-History": with_calls(auprc_rec(full_sc), n),
            "Coreset": with_calls(auprc_rec(core_sc), n),
            "Periodic": {**with_calls(auprc_rec(per_sc), n - len(periodic_skip)),
                         "mal_missed": sum(1 for i, x in enumerate(camps) if x["mal"] and i in periodic_skip)},
            "ATTP": {**with_calls(auprc_rec(attp_sc), attp_trig),
                     "mal_missed": sum(1 for x in camps if x["mal"] and x["F"] <= c.R_S)},
        },
        "vertical_only_ablation": {"TP": v_tp, "FP": v_fp, "FN": v_fn, "TN": v_tn,
                                   "recall": v_tp / P if P else 0, "FPR": v_fp / (n - P) if (n - P) else 0},
    }
    p = c.save_json(_out_name(), res)
    print(f"[RQ3 final {SPLIT}] campaigns={n} (mal={P} ben={n-P}) events={E}")
    for m, v in res["methods"].items():
        print(f"  {m:<13} AUPRC={v['AUPRC']:.3f}  Rec@5%FPR={v['Rec@5%FPR']:.3f}  "
              f"calls={v['calls']}  /1K={v['calls_per_1k']}" +
              (f"  (mal_missed={v['mal_missed']})" if "mal_missed" in v else ""))
    vo = res["vertical_only_ablation"]
    print(f"  Vertical-Only: recall={vo['recall']:.3f} FPR={vo['FPR']:.3f} (TP/FP/FN/TN={v_tp}/{v_fp}/{v_fn}/{v_tn})")
    print(f"  -> {p}")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train_R_S")
    ap.add_argument("--results-root", default="")
    args = ap.parse_args()
    SPLIT = args.split
    ROOT = c.RQ_RES if args.results_root.lower() == "rq_results" else (None if not args.results_root else args.results_root)
    recompute()
