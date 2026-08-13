"""R_S 标定 × 累积公式（s² / s³ / s^1.5）：扫 R_S，报 recall / FPR / 每场景平均调用次数。

纯评测侧（gemini 现有 vertical_hop_scores），无 LLM。
- 应送横向：train_R_S（慢投毒/边界触发，malicious DID 应被触发）
- 不应误送：train_R_T 的 clean 场景（clean DID 不应被触发）

**每场景调用次数** = 该场景所有 DID 的横向触发次数之和。一节点可多次触发：
F=Σ(sub-R_T s^p) 每次 cross R_S（且累积跳数≥2）计一次 confirm，随后 reset 再累积。
"""
from __future__ import annotations

import json
from collections import defaultdict

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402

R_T = 7.0
R0 = 0.95
MIN_VOL = 2  # 触发最少累积跳数（与 orchestrator _MIN_TRIGGER_VOLUME 一致）
FORMULAS = [("linear (s¹)", 1.0, (3, 60, 3)),
            ("p1.5 (s^1.5)", 1.5, (1, 25, 1)),
            ("square (s²)", 2.0, (5, 120, 5)),
            ("p2.5 (s^2.5)", 2.5, (50, 500, 25)),
            ("cube (s³)", 3.0, (25, 600, 25)),
            ("p3.5 (s^3.5)", 3.5, (150, 1500, 75)),
            ("p4 (s^4)", 4.0, (300, 3000, 150))]


def did_triggers(sub_rt_scores: list[float], p: float, r_s: float) -> int:
    """sub_rt_scores: 该 DID 的 sub-R_T 跳分数（trace 序）。返回触发次数（cross R_S 后 reset）。"""
    F = 0.0; vol = 0; trig = 0
    for s in sub_rt_scores:
        F += s ** p; vol += 1
        if F > r_s and vol >= MIN_VOL:
            trig += 1; F = 0.0; vol = 0  # confirm 后 reset
    return trig


def scenario_eval(ideal: dict, hops_by_did: dict, p: float, r_s: float):
    """返回 (mal_triggered, calls, mal_has_subrt)。
    mal_has_subrt: 恶意 DID 是否有 ≥1 sub-R_T 跳（需横向补；否则纵轴已抓，不计入 recall 分母）。"""
    mal = set(ideal["meta"]["malicious_dids"])
    calls = 0; mal_trig = False; mal_has_subrt = False
    for did, hops in hops_by_did.items():
        if ":agent:" not in did:
            continue
        # 必须按时序(trace_id)模拟累积，不能按分数排序（否则跨阈模式错、触发数错）
        sub_rt = [h["score"] for h in sorted(
            [h for h in hops if h["score"] <= R_T], key=lambda x: x["trace_id"])]
        if did in mal and sub_rt:
            mal_has_subrt = True
        t = did_triggers(sub_rt, p, r_s)
        calls += t
        if did in mal and t > 0:
            mal_trig = True
    return mal_trig, calls, mal_has_subrt


def load_split(split: str, category_filter: str = ""):
    """返回 [(sid, ideal, hops_by_did)]。hops_by_did 来自 gemini 现有 hop_scores。"""
    out = []
    for sid, scen, meta in c.scen_files(split):
        if category_filter and meta.get("category") != category_filter:
            continue
        hops = c.load_did_hops(sid)  # GEMINI_RES (train_R_S / train_R_T 均在此)
        if not hops:
            continue
        out.append((sid, {"meta": meta}, hops))
    return out


def sweep(slow, clean, p, rs_min, rs_max, rs_step):
    """recall 分母 = 恶意且有 sub-R_T 累积的场景（需横向补）；avg_calls 分母 = 全场景数。"""
    n_slow = len(slow)
    n_need = sum(1 for _, i, hops in slow
                 if any(did in set(i["meta"]["malicious_dids"]) and any(h["score"] <= R_T for h in hs)
                        for did, hs in hops.items() if ":agent:" in did))
    n_clean = len(clean)
    steps = int(round((rs_max - rs_min) / rs_step)) + 1
    rs_list = [round(rs_min + k * rs_step, 3) for k in range(steps)]
    rows = []
    for r_s in rs_list:
        trig = slow_calls = 0
        for _, ideal, hops in slow:
            mt, cll, has = scenario_eval(ideal, hops, p, r_s)
            if has:
                trig += 1 if mt else 0
            slow_calls += cll
        clean_trig = clean_calls = 0
        for _, ideal, hops in clean:
            _, cll, _ = scenario_eval(ideal, hops, p, r_s)
            any_trig = any(did_triggers(
                [h["score"] for h in sorted([h for h in hs if h["score"] <= R_T], key=lambda x: x["trace_id"])],
                p, r_s) > 0
                for did, hs in hops.items() if ":agent:" in did)
            clean_trig += 1 if any_trig else 0
            clean_calls += cll
        rows.append({"r_s": r_s,
                     "recall": trig / max(n_need, 1),          # 慢投毒送横向召回
                     "clean_fpr": clean_trig / max(n_clean, 1), # 干净场景误送率
                     "avg_calls": slow_calls / max(n_slow, 1),  # 每慢投毒场景平均调用
                     "clean_avg_calls": clean_calls / max(n_clean, 1)})  # 每干净场景平均调用
    return rows, n_need


def main():
    slow = load_split("train_R_S")
    clean = load_split("train_R_T", "clean")
    print("=" * 94)
    print(f"  R_S 标定 × 累积公式   R_T={R_T}  model=gemini  R0={R0}  (无 LLM, 评测侧重算)")
    print("=" * 94)
    print(f"  应送横向(train_R_S) {len(slow)} 场景 | 不应误送(train_R_T clean) {len(clean)} 场景")
    print(f"  recall 分母 = 恶意且有 sub-R_T 累积的场景（需横向补）；avg_calls 分母 = 全场景数\n")

    summary = {}
    for pname, p, (rmin, rmax, rstep) in FORMULAS:
        srows, n_need = sweep(slow, clean, p, rmin, rmax, rstep)
        # 推荐：recall≥R0 中 FPR 最低、再 calls 最少；若无，取 recall 最高的 FPR 最低点（knee）
        feas = [r for r in srows if r["recall"] >= R0]
        if feas:
            best = min(feas, key=lambda r: (r["clean_fpr"], r["avg_calls"]))
        else:
            max_r = max(r["recall"] for r in srows)
            cand = [r for r in srows if r["recall"] >= max_r - 1e-6]
            best = min(cand, key=lambda r: r["clean_fpr"])
        summary[pname] = {"p": p, "best": best, "rows": srows, "n_need": n_need}

        print(f"--- {pname}  (F = Σ sub-R_T s^{p:g})  需横向补场景={n_need} ---")
        print(f"{'r_s':>8} | {'慢投毒R':>8} {'干净FPR':>9} | {'慢场景avg调用':>13} {'干净场景avg调用':>15}")
        print("-" * 72)
        for r in srows:
            mark = "  <== 推荐" if r is best else ""
            print(f"{r['r_s']:>8} | {r['recall']:>8.3f} {r['clean_fpr']:>9.3f} | "
                  f"{r['avg_calls']:>13.2f} {r['clean_avg_calls']:>15.2f}{mark}")
        print(f">>> 推荐 R_S={best['r_s']}  R={best['recall']:.3f}  FPR={best['clean_fpr']:.3f}  "
              f"慢场景avg={best['avg_calls']:.2f}调用  干净avg={best['clean_avg_calls']:.2f}调用\n")

    print("=" * 94)
    print("  汇总（各公式推荐 R_S 下）")
    print(f"{'公式':<16}{'R_S':>7}{'慢投毒R':>9}{'干净FPR':>9}{'慢场景avg调用':>14}{'干净场景avg调用':>16}")
    print("-" * 72)
    for pname, s in summary.items():
        b = s["best"]
        print(f"{pname:<16}{b['r_s']:>7}{b['recall']:>9.3f}{b['clean_fpr']:>9.3f}"
              f"{b['avg_calls']:>14.2f}{b['clean_avg_calls']:>16.2f}")

    c.save_json("rq_rs_formulas.json",
                {"R_T": R_T, "R0": R0, "n_slow": len(slow), "n_clean": len(clean),
                 "formulas": {k: {"p": v["p"], "n_need": v["n_need"], "best": v["best"]}
                              for k, v in summary.items()}})
    print(f"\n>>> {c.RQ_RES / 'rq_rs_formulas.json'}")


if __name__ == "__main__":
    main()
