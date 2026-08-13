"""RQ3-test 第一步：test(te001-060) 纵向 V-Reasoner（隔离到 data/results/rq/gemini/）。

防卡死：每场景直接轮询 vertical_hop_scores 跳数（不用 _wait_vertical）+ 硬 deadline +
shutdown 超时 + 外层 asyncio.wait_for。卡住的场景跳过、可续跑。concurrency=4 降低聚合负载。
"""
from __future__ import annotations

import asyncio
import os
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
from intent_analysis.runners import evaluate  # noqa: E402


def _count_hops(db_path):
    try:
        cc = sqlite3.connect(str(db_path), timeout=1)
        n = cc.execute("SELECT COUNT(*) FROM vertical_hop_scores").fetchone()[0]
        cc.close(); return n
    except sqlite3.Error:
        return 0


async def _score_scenario(sid, ideal, model, client):
    temp_db = c.RQ_RES / f"{sid}_llm.db"
    if temp_db.exists():
        try: os.unlink(temp_db)
        except PermissionError: pass
    coord = await evaluate.build_coord(str(temp_db), model, client, c.R_T,
                                        concurrency=8, vertical_only=True)
    tracer = coord.vertical._tracer
    for t in ideal["traces"]:
        tid = await tracer.save_behavior_entry(
            session_id=t["session_id"], protocol_node_address=t["protocol_node_address"],
            sender_did=t["node_did"], target_did=t.get("target", ""),
            hop_count=[t["hop_count_a2a"], t["hop_count_intra"]],
            field_type=t["field_type"], content=t.get("content", ""),
            timestamp=t.get("timestamp", 0.0))
        await coord.enqueue_trace(t["session_id"], {
            "trace_id": tid, "session_id": t["session_id"], "sender_did": t["node_did"],
            "field_type": t["field_type"],
            "hop_count": [t["hop_count_a2a"], t["hop_count_intra"]],
            "content": t.get("content", ""), "target": t.get("target", ""),
            "timestamp": t.get("timestamp", 0.0)})
    expected = len(evaluate.action_trace_ids(ideal))
    deadline = time.time() + 170
    last, stable = -1, 0
    while time.time() < deadline:
        for sid_s in ideal["session_order"]:
            await coord.trigger_analysis_async(sid_s)
        await asyncio.sleep(2)
        n = _count_hops(temp_db)
        if n >= expected:
            break
        stable = stable + 1 if n == last else 0
        if stable >= 4:          # 跳数停滞 4 轮 → 放弃（防卡死）
            break
        last = n
    try:
        await asyncio.wait_for(coord.shutdown(), timeout=30)
    except asyncio.TimeoutError:
        pass
    return _count_hops(temp_db), expected


async def run_one(sid, scen, model, client, sem):
    ideal = c.load_ideal(scen)
    db = c.RQ_RES / f"{sid}_llm.db"
    if evaluate._vertical_done(db, ideal):
        return sid, "skip", _count_hops(db)
    async with sem:
        try:
            n, exp = await asyncio.wait_for(_score_scenario(sid, ideal, model, client), timeout=210)
            return sid, ("ok" if n >= exp else f"partial({n}/{exp})"), n
        except asyncio.TimeoutError:
            return sid, "timeout", _count_hops(db)


async def main():
    client, model = c.make_client()
    sem = asyncio.Semaphore(4)
    files = c.scen_files("test")
    print(f"[test vertical] {model}: {len(files)} scenarios (concurrency=4, R_S={c.R_S})", flush=True)
    t0 = time.time()
    results = await asyncio.gather(*[run_one(sid, scen, model, client, sem)
                                     for sid, scen, _ in files])
    done = sum(1 for _, s, _ in results if s in ("ok", "skip"))
    partial = [(s, st) for s, st, _ in results if st not in ("ok", "skip")]
    print(f"  finished {done}/{len(files)} ok in {time.time()-t0:.0f}s; partial/timeout={len(partial)}", flush=True)
    for s, st in partial[:20]:
        print(f"   {s}: {st}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
