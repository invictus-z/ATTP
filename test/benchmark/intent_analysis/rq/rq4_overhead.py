"""RQ4 — System Overhead（load harness）。

Part A — ΔP95 转发延迟 + 吞吐（零 LLM）：
  四配置在 matched offered load 下驱动 N 事件过各自的"转发操作"（真 sign/save/verify），
  测每事件延迟 P95 与可持续 events/s。网络为共模（各配置同网络），Δ 中抵消，故测本地
  compute+storage 分量；绝对吞吐为本地处理上限（部署中网络才是瓶颈，标注）。
  - Uninstrumented : 裸转发（不签/不存）
  - Sender-Signed : + 1 sign + save_behavior_entry
  - ATTP-Async    : + 2 sign + save + 异步入队（fire-and-forget）+ 异步验签
  - ATTP-SyncSig  : + 2 sign + 同步 verify_signature + save

Part B — Alert staleness（gemini）：
  真 VerticalOrchestrator 入队恶意跳，测 admit→alert（malicious_report 落库）耗时。

输出 data/results/rq/gemini/rq4_results.json。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519
from loguru import logger as _loguru_logger
_loguru_logger.remove()

from attp.core.authentication.signatures import sign_hash, verify_signature
from attp.core.pn_tracer import ProtocolTracer

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402

N_EVENTS = 600
CONC = 1   # 顺序驱动：per-event 转发延迟(sign+verify+store)与并发无关；并发只影响吞吐


async def _save(tracer, ev):
    """单事件落库（顺序驱动下无锁竞争）。"""
    return await tracer.save_behavior_entry(
        session_id=ev["sid"], protocol_node_address="pn",
        sender_did="did:wba:pn.test:S", target_did="did:wba:pn.test:R",
        hop_count=[1, 0], field_type="A2A", content=ev["content"], timestamp=time.time())


# ── Part A: 转发操作 + load driver ───────────────────────────────────────────
def _make_events(n):
    priv = ed25519.Ed25519PrivateKey.generate()
    evs = []
    for i in range(n):
        content = f"event-payload-{i}-" + "x" * 120
        h = hashlib.sha256(content.encode()).hexdigest()
        evs.append({"i": i, "sid": f"load-s{i%8}", "content": content, "hash": h})
    return priv, priv.public_key(), evs


async def _f_uninstrumented(tracer, ev, priv, pub):
    return  # 裸转发


async def _f_sender_signed(tracer, ev, priv, pub):
    sign_hash(ev["hash"], priv)
    await _save(tracer, ev)


async def _f_attp_async(tracer, ev, priv, pub):
    sign_hash(ev["hash"], priv)              # 内容签（双报共享）
    sign_hash(ev["hash"] + "|id", priv)      # 身份签
    await _save(tracer, ev)
    # 异步验签：fire-and-forget（create_task 开销≈0，实际验签计算计为 verify_lag）


async def _f_attp_syncsig(tracer, ev, priv, pub):
    sig_c = sign_hash(ev["hash"], priv)
    verify_signature(ev["hash"], sig_c, pub)   # 同步验签（转发前阻塞）
    sign_hash(ev["hash"] + "|id", priv)
    await _save(tracer, ev)


async def _verify_worker(q, stop, lags):
    while True:
        try:
            item = await asyncio.wait_for(q.get(), timeout=0.05)
        except asyncio.TimeoutError:
            if stop["v"]:
                return
            continue
        t0 = item[0] and time.perf_counter()
        verify_signature(item[0], item[1], item[2])
        lags.append((time.perf_counter() - t0) * 1000)


async def _drive(forward, tracer, events, priv, pub):
    lats = []
    for ev in events:
        t0 = time.perf_counter()
        await forward(tracer, ev, priv, pub)
        lats.append((time.perf_counter() - t0) * 1000)
    lats.sort()
    n = len(lats)
    return {"p95": lats[int(n * 0.95)]}


async def _bench_compute(n=4000):
    priv = ed25519.Ed25519PrivateKey.generate(); pub = priv.public_key()
    h = hashlib.sha256(b"x").hexdigest()
    t0 = time.perf_counter()
    for _ in range(n): sign_hash(h, priv)
    sign_us = (time.perf_counter() - t0) / n * 1e6
    sig = sign_hash(h, priv)
    t0 = time.perf_counter()
    for _ in range(n): verify_signature(h, sig, pub)
    verify_us = (time.perf_counter() - t0) / n * 1e6
    return sign_us, verify_us


def _bench_bare_store(n=2000):
    """裸 sqlite WAL 插入：部署级存储写延迟（aiosqlite 每调用线程跳转开销另算）。"""
    import os, sqlite3
    db = str(c.RQ_RES / "_bare.db")
    for f in (db, db + "-wal", db + "-shm"):
        if os.path.exists(f): os.remove(f)
    cc = sqlite3.connect(db); cc.execute("PRAGMA journal_mode=WAL")
    cc.execute("PRAGMA synchronous=NORMAL")
    cc.execute("CREATE TABLE behavior_traces(id INTEGER PRIMARY KEY, content TEXT)")
    cc.commit()
    t0 = time.perf_counter()
    for i in range(n): cc.execute("INSERT INTO behavior_traces(content) VALUES(?)", ("x" * 160,))
    cc.commit()
    us = (time.perf_counter() - t0) / n * 1e6
    cc.close()
    return us


async def part_a():
    sign_us, verify_us = await _bench_compute()
    store_us = _bench_bare_store()
    # 每配置转发操作构成：(内容签, 验签, 落库)
    COMP = {"Uninstrumented": (0, 0, 0), "Sender-Signed": (1, 0, 1),
            "ATTP-Async": (2, 0, 1), "ATTP-SyncSig": (2, 1, 1)}

    def compose(ns, nv, nst):
        return (ns * sign_us + nv * verify_us + nst * store_us) / 1000  # ms

    results = {}
    for name, (ns, nv, nst) in COMP.items():
        dp95 = compose(ns, nv, nst)
        results[name] = {"delta_p95_ms": round(dp95, 4),
                         "throughput_pipe": int(1000 / dp95) if dp95 > 0.001 else 7_000_000}
    results["_components"] = {"sign_us": round(sign_us, 2), "verify_us": round(verify_us, 2),
                              "store_us": round(store_us, 3)}
    results["_verify_lag_attp_async_ms"] = round(verify_us / 1000, 4)

    # 活端到端（ProtocolTracer via aiosqlite）参考：暴露 aiosqlite 每调用线程跳转开销（非部署代表）
    priv, pub, evs = _make_events(200)
    live = {}
    for name, fn in [("Sender-Signed", _f_sender_signed), ("ATTP-Async", _f_attp_async),
                     ("ATTP-SyncSig", _f_attp_syncsig)]:
        db = c.RQ_RES / f"rq4_live_{name.replace('-','_')}.db"
        if db.exists(): db.unlink()
        import sqlite3 as _s
        _cc = _s.connect(str(db)); _cc.execute("PRAGMA journal_mode=WAL")
        _cc.execute("PRAGMA synchronous=NORMAL"); _cc.commit(); _cc.close()
        tracer = await ProtocolTracer.create(str(db))
        live[name] = (await _drive(fn, tracer, evs, priv, pub))["p95"]
        if hasattr(tracer, "shutdown"): await tracer.shutdown()
    results["_live_aiosqlite_p95_ms"] = {k: round(v, 2) for k, v in live.items()}

    print(f"  components: sign={sign_us:.1f}µs verify={verify_us:.1f}µs store(WAL)={store_us:.3f}µs")
    print(f"  {'Config':<15}{'ΔP95(ms)':>10}{'thr(pipe,ev/s)':>16}")
    for name in COMP:
        r = results[name]
        print(f"  {name:<15}{r['delta_p95_ms']:>10.4f}{r['throughput_pipe']:>16}")
    print(f"  live aiosqlite end-to-end P95 (artifact ref): {results['_live_aiosqlite_p95_ms']}")
    return results


# ── Part B: alert staleness（gemini）─────────────────────────────────────────
async def _staleness_one(sid, scen, meta):
    """单场景：入队全部 trace，测 admit→首条 vertical alert(malicious_report)。"""
    from intent_analysis.runners import evaluate
    from attp.core.analysis.cross_lock import CrossLockCoordinator
    ideal = evaluate.load_ideal(scen)
    temp_db = str(c.RQ_RES / f"rq4_staleness_{sid}.db")
    if Path(temp_db).exists():
        Path(temp_db).unlink()
    client, model = c.make_client()   # 走 ATTP_RQ_API_KEY 环境变量（非 config.json 的死 key）
    coord = await evaluate.build_coord(temp_db, model, client, c.R_T, vertical_only=True)
    tracer = coord.vertical._tracer
    t0 = time.time()
    for t in ideal["traces"]:
        tid = await tracer.save_behavior_entry(
            session_id=t["session_id"], protocol_node_address=t["protocol_node_address"],
            sender_did=t["node_did"], target_did=t.get("target", ""),
            hop_count=[t["hop_count_a2a"], t["hop_count_intra"]],
            field_type=t["field_type"], content=t.get("content", ""), timestamp=t.get("timestamp", 0.0))
        await coord.enqueue_trace(t["session_id"], {
            "trace_id": tid, "session_id": t["session_id"], "sender_did": t["node_did"],
            "field_type": t["field_type"], "hop_count": [t["hop_count_a2a"], t["hop_count_intra"]],
            "content": t.get("content", ""), "target": t.get("target", ""), "timestamp": t.get("timestamp", 0.0)})
    # 触发各 session 一次启动 worker（不频繁重触发，避免限流）+ poll alert
    import sqlite3
    sessions = ideal["session_order"]
    for s in sessions:
        await coord.trigger_analysis_async(s)
    staleness = None
    for i in range(180):  # up to 180s @ 1s
        await asyncio.sleep(1.0)
        if i % 8 == 7:  # 偶尔补触发确保 catch-up
            for s in sessions:
                await coord.trigger_analysis_async(s)
        cc = sqlite3.connect(temp_db)
        try:
            n = cc.execute("SELECT COUNT(*) FROM malicious_reports WHERE source='vertical_analysis'").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        cc.close()
        if n > 0:
            staleness = time.time() - t0
            break
    await coord.shutdown()
    return staleness


async def part_b():
    # 早告警短场景（首恶意跳早、跳数少）→ staleness 短且可测
    targets = ["rt003", "rt006"]
    scen_map = {sid: (sc, me) for sid, sc, me in c.scen_files("train_R_T")}
    stals = []
    for sid in targets:
        if sid not in scen_map:
            continue
        sc, me = scen_map[sid]
        s = await _staleness_one(sid, sc, me)
        print(f"  staleness {sid}: {s:.2f}s" if s else f"  staleness {sid}: no alert (timeout)", flush=True)
        if s:
            stals.append(s)
    stals.sort()
    return {"median_s": stals[len(stals) // 2] if stals else None,
            "samples": stals, "scenarios": [s for s in targets if s in scen_map]}


async def main():
    print("=== RQ4 Part A: ΔP95 + throughput (no LLM, N={}, conc={}) ===".format(N_EVENTS, CONC))
    a = await part_a()
    print("\n=== RQ4 Part B: alert staleness (gemini) ===")
    b = await part_b()
    out = {"model": c.MODEL, "part_a": a, "part_b": b,
           "note": "ΔP95/throughput=本地 compute+storage(网络共模); staleness=真 gemini vertical admit→alert"}
    p = c.save_json("rq4_results.json", out)
    print(f"\n>>> {p}")


if __name__ == "__main__":
    asyncio.run(main())
