"""RQ3 各横向机制的输入 token 消耗（test，gemini，cl100k_base 计数）。

重构每个 confirm 的完整 prompt（system+user），tiktoken 数 token，无需再调 API。
- Full-History : 全 DID，全跳 sessions_data
- Coreset      : 全 DID，每会话 top-M 跳
- Periodic     : 预算匹配漏审部分 DID，被审 DID 用全跳
- ATTP         : 风险触发(F>R_S) DID，全跳
"""
import sqlite3
import tiktoken

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402
from attp.core.analysis.horizontal.prompts import CONFIRMATION_PROMPT
from attp.core.analysis.horizontal.analyzer import HorizontalIntentAnalyzer

enc = tiktoken.get_encoding("cl100k_base")
SYSTEM = "你是一个多Agent系统的跨Session安全审计专家，只输出 JSON，不输出任何其他内容。"
SYS_TOK = len(enc.encode(SYSTEM))
M = 3  # coreset top-M


def tok_for(sessions_data, did):
    if not sessions_data:
        return 0
    summary = HorizontalIntentAnalyzer._format_sessions(sessions_data)
    prompt = CONFIRMATION_PROMPT.format(
        did=did, node_type="agent", session_count=len(sessions_data),
        context="（首次确认，无前序上下文）", prior_report="（首次确认，无前序批次）",
        sessions_summary=summary)
    return SYS_TOK + len(enc.encode(prompt))


def main():
    # 收集 test 节点（按到达序，与 rq3_recompute 一致）
    camps = []
    for sid, scen, meta in c.scen_files("test"):
        mal = set(meta["malicious_dids"])
        content = c.load_content(sid, c.RQ_RES); intents = c.load_intents(sid, root=c.RQ_RES)
        for did, hs in c.load_did_hops(sid, c.RQ_RES).items():
            if ":agent:" not in did:
                continue
            camps.append({"sid": sid, "did": did, "mal": did in mal, "F": c.f_accumulation(hs),
                          "min_t": min(h["trace_id"] for h in hs), "hs": hs,
                          "content": content, "intents": intents})
    camps.sort(key=lambda x: x["min_t"])
    n = len(camps); n_scn = len({x["sid"] for x in camps})

    # 预算匹配 Periodic 漏审集（与 rq3_recompute 一致）
    attp_trig = sum(1 for x in camps if x["F"] > c.R_S)
    skip_target = max(0, n - attp_trig)
    step = max(2, round(n / max(1, skip_target))) if skip_target else n + 1
    periodic_skip = {i for i in range(n) if i % step == (step - 1)}

    methods = {"Full-History": [], "Coreset Reader": [], "Periodic-Horizontal": [], "ATTP": []}
    for i, x in enumerate(camps):
        full_sd = c.build_sessions_data(x["hs"], x["content"], x["intents"], "full")
        core_sd = c.build_sessions_data(x["hs"], x["content"], x["intents"], "coreset")
        methods["Full-History"].append(tok_for(full_sd, x["did"]))
        methods["Coreset Reader"].append(tok_for(core_sd, x["did"]))
        if i not in periodic_skip:
            methods["Periodic-Horizontal"].append(tok_for(full_sd, x["did"]))
        if x["F"] > c.R_S:
            methods["ATTP"].append(tok_for(full_sd, x["did"]))

    print("=" * 86)
    print(f"  RQ3 各横向机制 输入 token 消耗（test, gemini, cl100k_base 计数）  nodes={n} scenarios={n_scn}")
    print("=" * 86)
    print(f"{'Method':<20}{'calls':>7}{'总token':>12}{'avg token/场景':>16}{'avg token/call':>16}")
    print("-" * 86)
    out = {}
    for m, toks in methods.items():
        total = sum(toks); calls = len(toks)
        per_scn = total / n_scn
        per_call = total / calls if calls else 0
        out[m] = {"calls": calls, "total": total, "per_scenario": per_scn, "per_call": per_call}
        print(f"{m:<20}{calls:>7}{total:>12}{per_scn:>16.0f}{per_call:>16.0f}")
    c.save_json("rq3_tokens.json", out)


if __name__ == "__main__":
    main()
