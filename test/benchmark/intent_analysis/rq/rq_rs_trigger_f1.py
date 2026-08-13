"""各公式最佳 R_S 下，按正常触发机制离线横向(触发+confirm)的节点级 F1。

关键（纠正复用错误）：不同公式触发点不同 → 每次 confirm 看到**该触发批次**的跳（条数不同）→ taint 不同。
故对每个 (公式, 节点, 触发事件) 独立调 gemini confirm，不复用全量 taint。

模拟触发：DID 的 sub-R_T 跳按序累加 F=Σs^p；F>R_S 且累积≥2 跳时触发一次，
confirm 看**本批次跳**（自上次 reset 起），随后 reset。节点 flagged = 任一触发 taint≥5.5。
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
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
from intent_analysis.rq.rq3_scorer import _confirm  # 复用 confirm 调用（含 429 退避）

R_T = 7.0
CONFIRM_TH = 5.5
MIN_VOL = 2
BEST = [("linear", 1.0, 9.0), ("p1.5", 1.5, 23.0), ("square", 2.0, 45.0),
        ("p2.5", 2.5, 100.0), ("cube", 3.0, 200.0), ("p3.5", 3.5, 375.0), ("p4", 4.0, 600.0)]
_DB = c.RQ_RES / "rq_rs_trigger_f1.db"


def _init():
    conn = sqlite3.connect(str(_DB))
    conn.execute("CREATE TABLE IF NOT EXISTS tc (formula TEXT, sid TEXT, did TEXT, bi INT, "
                 "taint REAL, mal INT, PRIMARY KEY(formula,sid,did,bi))")
    conn.commit(); conn.close()


def _done():
    conn = sqlite3.connect(str(_DB)); conn.row_factory = sqlite3.Row
    out = {(r["formula"], r["sid"], r["did"], r["bi"]): (r["taint"], r["mal"])
           for r in conn.execute("SELECT formula,sid,did,bi,taint,mal FROM tc")}
    conn.close(); return out


def _save(formula, sid, did, bi, taint, mal):
    conn = sqlite3.connect(str(_DB))
    conn.execute("INSERT OR REPLACE INTO tc(formula,sid,did,bi,taint,mal) VALUES(?,?,?,?,?,?)",
                 (formula, sid, did, bi, taint, mal))
    conn.commit(); conn.close()


def trigger_batches(sub_hops, p, r_s):
    """返回触发批次列表（每批 = 自上次 reset 起的跳）。"""
    F = 0.0; vol = 0; batch = []; batches = []
    for h in sub_hops:
        F += h["score"] ** p; vol += 1; batch.append(h)
        if F > r_s and vol >= MIN_VOL:
            batches.append(batch); F = 0.0; vol = 0; batch = []
    return batches


def collect_jobs():
    """返回 [(formula, sid, did, bi, sessions_data, is_mal)]。"""
    jobs = []
    for pname, p, r_s in BEST:
        for sid, scen, meta in c.scen_files("train_R_S"):
            mal = set(meta["malicious_dids"])
            content = c.load_content(sid); intents = c.load_intents(sid)
            hops_by_did = c.load_did_hops(sid)
            for did, hs in hops_by_did.items():
                if ":agent:" not in did:
                    continue
                sub = sorted([h for h in hs if h["score"] <= R_T], key=lambda x: x["trace_id"])
                for bi, batch in enumerate(trigger_batches(sub, p, r_s)):
                    sd = c.build_sessions_data(batch, content, intents, "full")
                    jobs.append((pname, sid, did, bi, sd, did in mal))
    return jobs


async def _run_one(client, model, formula, sid, did, bi, sd, is_mal, sem, state):
    taint = await _confirm(client, model, did, sd, sem)
    _save(formula, sid, did, bi, 0.0 if taint is None else taint, 1 if is_mal else 0)
    state["n"] += 1
    if state["n"] % 80 == 0:
        print(f"  {state['n']}/{state['total']}  ({time.time()-state['t0']:.0f}s)", flush=True)


async def run():
    _init()
    done = _done()
    client, model = c.make_client()
    sem = asyncio.Semaphore(10)
    jobs = collect_jobs()
    todo = [j for j in jobs if (j[0], j[1], j[2], j[3]) not in done]
    print(f"[trigger-F1] {model}: {len(jobs)} trigger-confirm jobs total, {len(todo)} to run", flush=True)
    state = {"n": 0, "total": len(todo), "t0": time.time()}
    await asyncio.gather(*[_run_one(client, model, f, s, d, b, sd, m, sem, state)
                           for f, s, d, b, sd, m in todo])
    print(f"  done in {time.time()-state['t0']:.0f}s", flush=True)


def aggregate():
    done = _done()
    # 节点 flagged per formula = 任一触发 taint>=5.5
    nodes = {}  # (formula, sid, did) -> {mal, flagged, n_trig, n_hops_per_trig}
    for (formula, sid, did, bi), (taint, mal) in done.items():
        k = (formula, sid, did)
        d = nodes.setdefault(k, {"mal": bool(mal), "flagged": False, "n_trig": 0, "hops": []})
        d["n_trig"] += 1
        d["hops"].append(taint)
        if taint >= CONFIRM_TH:
            d["flagged"] = True
    # 节点全集（含 0 触发的）：从 train_R_S 重建
    all_nodes = set()
    for sid, scen, meta in c.scen_files("train_R_S"):
        mal = set(meta["malicious_dids"])
        for did in c.load_did_hops(sid):
            if ":agent:" not in did:
                continue
            all_nodes.add((sid, did, did in mal))
    print("\n" + "=" * 90)
    print(f"  离线横向(正常触发+confirm)节点级 F1 × 公式   train_R_S 节点={len(all_nodes)}")
    print(f"  flagged = 该公式下任一触发批次 confirm taint≥{CONFIRM_TH}")
    print("=" * 90)
    print(f"{'公式':<12}{'R_S':>6} | {'P':>7}{'R':>8}{'F1':>8}{'FPR':>8} | {'TP/FP/FN/TN':>13}"
          f"{'触发节点(mal/ben)':>20}{'avg触发批次跳数':>16}")
    print("-" * 90)
    out = {}
    for pname, p, r_s in BEST:
        tp = fp = fn = tn = 0; mal_trig = ben_trig = 0; hopcount = []; ntrig = 0
        for (sid, did, is_mal) in all_nodes:
            d = nodes.get((pname, sid, did))
            flagged = d["flagged"] if d else False
            trig = d["n_trig"] if d else 0
            if is_mal and trig: mal_trig += 1
            if (not is_mal) and trig: ben_trig += 1
            if is_mal and flagged: tp += 1
            elif is_mal and not flagged: fn += 1
            elif (not is_mal) and flagged: fp += 1
            else: tn += 1
        P = tp/(tp+fp) if tp+fp else 0; R = tp/(tp+fn) if tp+fn else 0
        F1 = 2*P*R/(P+R) if P+R else 0; FPR = fp/(fp+tn) if fp+tn else 0
        # avg 触发批次跳数（从 jobs 的 sessions_data 重算太重；用近似：总触发数已知，跳数需另存）
        out[pname] = {"R_S": r_s, "P": P, "R": R, "F1": F1, "FPR": FPR,
                      "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                      "mal_trig_nodes": mal_trig, "ben_trig_nodes": ben_trig}
        print(f"{pname:<12}{r_s:>6} | {P:>7.3f}{R:>8.3f}{F1:>8.3f}{FPR:>8.3f} | "
              f"{tp:>3}/{fp:>3}/{fn:>3}/{tn:<3}     {mal_trig:>3}/{sum(1 for _,_,m in all_nodes if m):<3}  "
              f"{ben_trig:>3}/{sum(1 for _,_,m in all_nodes if not m):<3}"
              f"{'(见 json)':>16}")
    c.save_json("rq_rs_trigger_f1.json", {"confirm_th": CONFIRM_TH, "formulas": out})


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="run", choices=["run", "agg", "count"])
    args = ap.parse_args()
    if args.mode == "count":
        jobs = collect_jobs()
        from collections import Counter
        cnt = Counter(j[0] for j in jobs)
        print("trigger-confirm jobs per formula:", dict(cnt), "total:", len(jobs))
    elif args.mode == "run":
        asyncio.run(run())
        aggregate()
    else:
        aggregate()
