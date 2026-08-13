"""打分侧消融：动态意图 / 历史摘要 对 V-Reasoner 评分的贡献（test，gemini）。

- no_intent  : 禁用动态意图（intent_revisions=[]），保留 hidden_state 递推
- no_hidden  : 禁用历史摘要（hidden_state_prev 恒空），保留动态意图
baseline(full) = 两者都开 = 现有 test 纵向（Macro-F1=0.434，同 prompt）。

复用已抽取的真实 intent_revisions（vertical_analysis_states），不重抽意图。
hidden_state 按 session 时序递推（no_hidden 除外）。
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import time
from collections import defaultdict
from loguru import logger
logger.remove()
logger.add(sys.stderr, level="WARNING")

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402
from intent_analysis.runners import evaluate  # noqa: E402
from attp.core.analysis.vertical import VerticalIntentAnalyzer

R_T = 7.0; TAU = 1.0
ABLATIONS = ["no_intent", "no_hidden"]
SPLIT = "test"
ROOT = None      # None=GEMINI_RES(train_R_T), c.RQ_RES(test)
_DB = c.RQ_RES / f"rq_ablation_vreasoner_{SPLIT}.db"


def _init():
    conn = sqlite3.connect(str(_DB))
    conn.execute("CREATE TABLE IF NOT EXISTS ab (ablation TEXT, sid TEXT, trace_id INT, score REAL, "
                 "PRIMARY KEY(ablation,sid,trace_id))")
    conn.commit(); conn.close()


def _done(ablation):
    conn = sqlite3.connect(str(_DB)); conn.row_factory = sqlite3.Row
    out = {(r["sid"], r["trace_id"]): r["score"]
           for r in conn.execute("SELECT sid,trace_id,score FROM ab WHERE ablation=?", (ablation,))}
    conn.close(); return out


def _save(ablation, sid, tid, score):
    conn = sqlite3.connect(str(_DB))
    conn.execute("INSERT OR REPLACE INTO ab(ablation,sid,trace_id,score) VALUES(?,?,?,?)",
                 (ablation, sid, tid, score))
    conn.commit(); conn.close()


def load_sessions():
    """[(sid, [(hop_dict, applicable_revisions)], ideal)]——action 跳按时序。"""
    out = []
    for sid, scen, meta in c.scen_files(SPLIT):
        ideal = c.load_ideal(scen)
        # 原始 intent_revisions per session（已抽取，存于 rq_results vertical_analysis_states）
        rdb = c.results_db(sid, ROOT)
        revs_by_sess = defaultdict(list)
        if rdb.exists():
            cc = sqlite3.connect(str(rdb)); cc.row_factory = sqlite3.Row
            for r in cc.execute("SELECT session_id, intent_revisions_json FROM vertical_analysis_states"):
                try:
                    for rv in json.loads(r["intent_revisions_json"] or "[]"):
                        revs_by_sess[r["session_id"]].append(rv)
                except (json.JSONDecodeError, TypeError):
                    pass
            # behavior_traces -> hop dict
            traces = [dict(r) for r in cc.execute(
                "SELECT id,session_id,node_did,field_type,content,target,"
                "hop_count_a2a,hop_count_intra,timestamp FROM behavior_traces ORDER BY id")]
            cc.close()
        hops_with_rev = []
        for t in traces:
            hd = {"trace_id": t["id"], "session_id": t["session_id"], "sender_did": t["node_did"],
                  "field_type": t["field_type"], "content": t.get("content", ""),
                  "target": t.get("target", ""), "session_id_": t["session_id"],
                  "hop_count": [t["hop_count_a2a"], t["hop_count_intra"]], "timestamp": t.get("timestamp", 0.0)}
            revs = [rv for rv in revs_by_sess.get(t["session_id"], [])
                    if (rv.get("source") or {}).get("trace_id", 0) <= t["id"]]
            hops_with_rev.append((hd, revs))
        out.append((sid, hops_with_rev, ideal))
    return out


async def score_session(analyzer, sid, hops_rev, ablation, sem):
    """按时序评分一 session；no_intent 禁意图、no_hidden 禁隐状态。返回 [(tid,score)]。"""
    hidden = ""  # session 起始
    results = []
    for hd, revs in hops_rev:
        tid = hd["trace_id"]
        ir = [] if ablation == "no_intent" else revs
        hs = "" if ablation == "no_hidden" else hidden
        async with sem:
            try:
                sc = await analyzer.score_hop(hd, ir, hs)
            except Exception:
                sc = None
        if sc is not None:
            _save(ablation, sid, tid, sc.score)
            results.append((tid, sc.score))
            if ablation != "no_hidden":
                hidden = sc.hidden_state or hidden  # 递推（no_hidden 不递推）
        else:
            _save(ablation, sid, tid, -1.0)
    return results


async def run():
    _init()
    client, model = c.make_client()
    analyzer = VerticalIntentAnalyzer(client=client, model=model)
    sem = asyncio.Semaphore(10)
    sessions = load_sessions()
    # 只评 action 跳（与生产一致：非发起者 U2A）
    action_sets = {sid: set(evaluate.action_trace_ids(ideal)) for sid, _, ideal in sessions}
    for ablation in ABLATIONS:
        done = _done(ablation)
        pending = [(sid, [(hd, rv) for hd, rv in hops_rev if hd["trace_id"] in action_sets[sid]
                          and (sid, hd["trace_id"]) not in done])
                   for sid, hops_rev, _ in sessions]
        n = sum(len(p) for _, p in pending)
        print(f"[{ablation}] {model}: {n} hops to score", flush=True)
        t0 = time.time()
        await asyncio.gather(*[score_session(analyzer, sid, hops, ablation, sem)
                               for sid, hops in pending if hops])
        print(f"  {ablation} done in {time.time()-t0:.0f}s", flush=True)


def macro_f1(sid_scores, sessions):
    """sid_scores: {(sid,tid):score}。返回 Macro-F1（偏离类，{偏离,干净}）。"""
    tp = fp = fn = tn = 0
    for sid, _, ideal in sessions:
        hi = {int(k): v for k, v in ideal["meta"]["hop_ideals"].items()}
        for tid in evaluate.action_trace_ids(ideal):
            truth = tid in hi and hi[tid]["s"] > TAU
            pred = sid_scores.get((sid, tid), -1) > R_T
            if truth and pred: tp += 1
            elif truth and not pred: fn += 1
            elif not truth and pred: fp += 1
            else: tn += 1
    return c.macro_f1_binary(tp, fp, fn, tn), (tp, fp, fn, tn)


def aggregate():
    sessions = load_sessions()
    # baseline (full) = 现有 test 纵向
    base = {}
    for sid, _, _ in sessions:
        rdb = c.results_db(sid, ROOT)
        if not rdb.exists():
            continue
        cc = sqlite3.connect(str(rdb))
        for tid, sc in cc.execute("SELECT trace_id,score FROM vertical_hop_scores"):
            base[(sid, tid)] = sc
        cc.close()
    mf_b, cm_b = macro_f1(base, sessions)
    print("\n" + "=" * 80)
    print(f"  V-Reasoner 打分侧消融（test, gemini, R_T={R_T}）  Macro-F1 = {{偏离,干净}} 宏平均")
    print("=" * 80)
    print(f"{'配置':<14}{'Macro-F1':>10}{'Δ vs full':>11}{'TP/FP/FN/TN':>16}")
    print("-" * 80)
    print(f"{'full(baseline)':<14}{mf_b:>10.3f}{'--':>11}{cm_b[0]}/{cm_b[1]}/{cm_b[2]}/{cm_b[3]}")
    out = {"full": {"macro_f1": mf_b, "cm": cm_b}}
    for ab in ABLATIONS:
        sc = _done(ab)
        sc = {k: v for k, v in sc.items() if v >= 0}
        mf, cm = macro_f1(sc, sessions)
        print(f"{ab:<14}{mf:>10.3f}{mf-mf_b:>+11.3f}{cm[0]}/{cm[1]}/{cm[2]}/{cm[3]}")
        out[ab] = {"macro_f1": mf, "delta": mf - mf_b, "cm": cm}
    c.save_json("rq_ablation_vreasoner.json", out)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="run", choices=["run", "agg"])
    ap.add_argument("--split", default="test")
    args = ap.parse_args()
    SPLIT = args.split
    ROOT = c.RQ_RES if SPLIT == "test" else None
    _DB = c.RQ_RES / f"rq_ablation_vreasoner_{SPLIT}.db"
    if args.mode == "run":
        asyncio.run(run())
    aggregate()
