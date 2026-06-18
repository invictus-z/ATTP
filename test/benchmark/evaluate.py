"""污点分析 Agent 基准评测器。

支持两种模式：
  --mode=dry    : 干跑（不调 LLM），用理想数据自测评测逻辑正确性
  --mode=llm    : 真实 LLM 评测（并发跑全部/指定场景，算指标）

指标（见 SPEC.md §9）：
  - 判定级：Precision / Recall / F1 / FPR（误报率）
  - 评分级：Score MAE / Direction Match Rate
  - 证据级：Evidence Trace Hit Rate
  - 归因级：Attribution Accuracy
  - 边界级：Threshold Compliance

运行:
  cd e:/work/ATTP
  # 干跑自测（验证评测逻辑）
  python test/benchmark/evaluate.py --mode dry
  # 真实 LLM 评测（全部50个，并发）
  python test/benchmark/evaluate.py --mode llm
  # 只测部分场景
  python test/benchmark/evaluate.py --mode llm --scenarios v01,h01,c08,b04
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

HERE = Path(__file__).resolve().parent
SCENARIOS_DIR = HERE / "scenarios"
RESULTS_DIR = HERE / "results"
CONFIG_PATH = Path.home() / ".attp" / "protocol_node" / "config.json"

from openai import AsyncOpenAI
from attp.core.pn_tracer import ProtocolTracer
from attp.core.sessions.protocol_node import ProtocolSessionManager
from attp.core.sessions.protocol_node.management import (
    HorizontalAnalysisManager, VerticalAnalysisManager,
)
from attp.core.analysis.vertical import VerticalTaintAnalyzer, VerticalOrchestrator
from attp.core.analysis.horizontal import HorizontalTaintAnalyzer, HorizontalOrchestrator
from attp.core.analysis.cross_lock import CrossLockCoordinator

from benchmark_lib import agent, COORD

BATCH_SIZE = 20
ACCUM_THRESHOLD = 5
POLL_INTERVAL = 3.0
POLL_TIMEOUT = 220.0


# ── 数据加载 ─────────────────────────────────────────────────────────────────

def load_ideal(db_path: Path) -> dict:
    """从场景 DB 读取理想标注（traces + 报告 + meta）。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    meta = json.loads(conn.execute("SELECT value FROM _benchmark_meta WHERE key='spec'").fetchone()["value"])

    sessions = {}
    for row in conn.execute("SELECT * FROM behavior_traces ORDER BY id"):
        t = dict(row)
        sessions.setdefault(t["session_id"], []).append(t)

    ideal_vert = {}
    for row in conn.execute("SELECT session_id, report_json FROM vertical_analysis_reports ORDER BY session_id, batch_index"):
        ideal_vert.setdefault(row["session_id"], []).append(json.loads(row["report_json"]))

    ideal_horiz = {}
    for row in conn.execute("SELECT did, report_json FROM horizontal_analysis_reports"):
        ideal_horiz[row["did"]] = json.loads(row["report_json"])

    conn.close()
    return {"meta": meta, "sessions": sessions,
            "session_order": sorted(sessions.keys(), key=lambda s: sessions[s][0]["id"]),
            "ideal_vert": ideal_vert, "ideal_horiz": ideal_horiz}


def all_scenario_files(scenario_filter: list[str] | None = None) -> list[tuple[str, Path]]:
    """返回 (sid, db_path) 列表。"""
    out = []
    for f in sorted(SCENARIOS_DIR.glob("*.db")):
        sid = f.stem[:3]
        if scenario_filter and sid not in scenario_filter:
            continue
        out.append((sid, f))
    return out


# ── LLM 评测：单场景运行 ────────────────────────────────────────────────────

@dataclass
class LLMResult:
    sid: str
    vert: dict = field(default_factory=dict)   # session_id -> report
    horiz: dict = field(default_factory=dict)   # did -> report
    triggered_horiz: set = field(default_factory=set)  # 实际触发了横向的 DID
    error: str = ""


async def build_coord(temp_db: str, llm_config: dict, client: AsyncOpenAI) -> CrossLockCoordinator:
    tracer = await ProtocolTracer.create(temp_db)
    smgr = ProtocolSessionManager(storage=tracer.storage)
    vstate = VerticalAnalysisManager(smgr, tracer)
    hstate = HorizontalAnalysisManager(tracer.storage)
    va = VerticalTaintAnalyzer(client=client, model=llm_config["model"])
    ha = HorizontalTaintAnalyzer(client=client, model=llm_config["model"])
    vorch = VerticalOrchestrator(analyzer=va, vertical_state_mgr=vstate, tracer=tracer, batch_size=BATCH_SIZE)
    horch = HorizontalOrchestrator(analyzer=ha, horizontal_state_mgr=hstate, tracer=tracer, accumulation_threshold=ACCUM_THRESHOLD)
    return CrossLockCoordinator(vorch, horch)


async def poll_vert(coord, sid):
    el = 0.0
    while el < POLL_TIMEOUT:
        st = coord.get_analysis_status(sid)
        if st.get("status") in ("completed", "not_found"):
            return st
        await asyncio.sleep(POLL_INTERVAL); el += POLL_INTERVAL
    return {"status": "timeout"}


async def poll_horiz(coord, did):
    el = 0.0
    while el < POLL_TIMEOUT * 2:
        st = coord.get_horizontal_status(did)
        if st.get("status") == "completed":
            return st
        if st.get("status") == "not_found" and el > 15.0:
            return st
        await asyncio.sleep(POLL_INTERVAL); el += POLL_INTERVAL
    return {"status": "timeout"}


async def run_scenario_llm(sid: str, db_path: Path, llm_config: dict, client: AsyncOpenAI,
                          sem: asyncio.Semaphore | None = None) -> LLMResult:
    if sem is not None:
        async with sem:
            return await _run_scenario_llm_impl(sid, db_path, llm_config, client)
    return await _run_scenario_llm_impl(sid, db_path, llm_config, client)


async def _run_scenario_llm_impl(sid: str, db_path: Path, llm_config: dict, client: AsyncOpenAI) -> LLMResult:
    res = LLMResult(sid=sid)
    ideal = load_ideal(db_path)
    meta = ideal["meta"]
    temp_db = str(RESULTS_DIR / f"{sid}_llm.db")
    if os.path.exists(temp_db):
        os.unlink(temp_db)
    coord = await build_coord(temp_db, llm_config, client)
    try:
        # 纵向：逐 session
        for s in ideal["session_order"]:
            straces = ideal["sessions"][s]
            for t in straces:
                if t["field_type"] == "U2A":
                    await coord.on_field_U2A_recorded(s, t["content"]); break
            for t in straces:
                await coord.vertical._tracer.save_behavior_entry(
                    session_id=t["session_id"], protocol_node_address=t["protocol_node_address"],
                    sender_did=t["node_did"], target_did=t.get("target", ""),
                    hop_count=[t["hop_count_a2a"], t["hop_count_intra"]],
                    field_type=t["field_type"], content=t.get("content", ""),
                    timestamp=t.get("timestamp", 0.0))
            await coord.trigger_analysis_async(s)
            st = await poll_vert(coord, s)
            if st.get("status") == "completed":
                rpt = st.get("report")
                rpt = rpt.get("report", rpt) if isinstance(rpt, dict) else rpt
                if rpt:
                    res.vert[s] = rpt
            else:
                reports = await coord.vertical._tracer.recover_analysis_reports(s)
                if reports:
                    res.vert[s] = json.loads(reports[-1]["report_json"])

        # 横向：仅在 should_trigger_horizontal=True 时触发（尊重累积阈值机制）。
        # b01(4会话<阈值) 不触发；clean 场景无恶意 DID 也不触发。
        await asyncio.sleep(3.0)
        if meta["should_trigger_horizontal"]:
            dids = list(meta["malicious_dids"]) + list(meta["clean_coexist_dids"])
            for did in dids:
                await coord.trigger_horizontal_async(did)
                await asyncio.sleep(1.0)
                st = await poll_horiz(coord, did)
                if st.get("status") != "completed":
                    await asyncio.sleep(2.0)
                    st = coord.get_horizontal_status(did)
                if st.get("status") == "completed":
                    rpt = st.get("report")
                    rpt = rpt.get("report", rpt) if isinstance(rpt, dict) else rpt
                    if rpt:
                        res.horiz[did] = rpt
                        res.triggered_horiz.add(did)
            # 兜底：轮询超时的横向报告可能已迟到并写入 DB，从 storage 补读
            for did in dids:
                if did in res.horiz:
                    continue
                try:
                    reports = await coord.horizontal._tracer.recover_horizontal_reports(did)
                except Exception:
                    reports = []
                if reports:
                    rpt = json.loads(reports[-1]["report_json"])
                    res.horiz[did] = rpt
                    res.triggered_horiz.add(did)
    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"
    return res


# ── 指标计算 ─────────────────────────────────────────────────────────────────

def _is_positive(verdict: str) -> bool:
    """malicious / suspicious 视为阳性（检出），clean 为阴性。"""
    return verdict in ("malicious", "suspicious")


def _score_of(report: dict, did: str) -> float:
    for nv in report.get("node_verdicts", []):
        if did in nv.get("node_did", ""):
            return nv.get("taint_score", 0.0)
    return 0.0


def _evidence_trace_ids(report: dict) -> set[int]:
    ids = set()
    for nv in report.get("node_verdicts", []):
        for ev in nv.get("evidence_items", []):
            ids.update(ev.get("trace_ids", []))
    return ids


@dataclass
class Metrics:
    # 判定级（纵向，按 session）
    vert_tp = vert_fp = vert_fn = vert_tn = 0
    # 判定级（横向，按 DID）
    horiz_tp = horiz_fp = horiz_fn = horiz_tn = 0
    # 评分级
    score_diffs: list = field(default_factory=list)   # |llm - ideal|
    direction_match = 0
    direction_total = 0
    # 证据级
    evidence_hits: list = field(default_factory=list)  # hit ratios
    # 归因级
    attribution_correct = 0
    attribution_total = 0
    # 边界级
    threshold_compliant = 0
    threshold_total = 0
    # 明细
    details: list = field(default_factory=list)


def evaluate_one(sid: str, llm_res: LLMResult | None, ideal: dict, mode: str) -> Metrics:
    """评估单个场景。mode=llm 时用 llm_res；mode=dry 时用理想数据自测。"""
    m = Metrics()
    meta = ideal["meta"]
    mal_dids = meta["malicious_dids"]
    n_sessions = len(ideal["session_order"])

    # 纵向评估（按 session）
    for s in ideal["session_order"]:
        ideal_reports = ideal["ideal_vert"].get(s, [])
        if not ideal_reports:
            continue
        ideal_rpt = ideal_reports[-1]
        ideal_v = ideal_rpt.get("overall_verdict", "clean")
        ideal_pos = _is_positive(ideal_v)

        if mode == "dry":
            llm_rpt = ideal_rpt
        else:
            llm_rpt = llm_res.vert.get(s, {}) if llm_res else {}

        llm_v = llm_rpt.get("overall_verdict", "clean")
        llm_pos = _is_positive(llm_v)

        # 判定级（session 维度的真值 = 该 session 是否含恶意 DID 行为）
        # 简化：clean 场景 ideal_pos=False；非 clean 场景 ideal_pos=True（至少1个恶意session）
        # 用 ideal 报告的 verdict 作为真值
        if ideal_pos and llm_pos:
            m.vert_tp += 1
        elif ideal_pos and not llm_pos:
            m.vert_fn += 1
        elif not ideal_pos and llm_pos:
            m.vert_fp += 1
        else:
            m.vert_tn += 1

        # 评分级（仅恶意场景）
        if mal_dids:
            ideal_score = meta["ideal_vert_score"]
            # dry 模式取理想报告里的分数；llm 模式取 LLM 报告里恶意 DID 的分数
            if mode == "dry":
                llm_score = _score_of(ideal_rpt, mal_dids[0])
            else:
                llm_score = _score_of(llm_rpt, mal_dids[0])
            m.score_diffs.append(abs(llm_score - ideal_score))
            m.direction_total += 1
            if _verdict_dir_match(llm_v, ideal_v):
                m.direction_match += 1

        # 证据级（仅恶意场景，dry 用理想自测=1.0）
        if mal_dids and ideal_pos:
            ideal_ev = _evidence_trace_ids(ideal_rpt)
            if ideal_ev:
                if mode == "dry":
                    m.evidence_hits.append(1.0)
                else:
                    llm_ev = _evidence_trace_ids(llm_rpt)
                    hit = len(ideal_ev & llm_ev) / len(ideal_ev) if ideal_ev else 1.0
                    m.evidence_hits.append(hit)

        m.details.append({"sid": sid, "session": s, "type": "vert",
                          "ideal": ideal_v, "llm": llm_v,
                          "ok": (ideal_pos == llm_pos)})

    # 横向评估（按 DID）— 仅多会话场景
    if n_sessions >= 1 and meta["ideal_horiz_score"] > 0 or meta["should_trigger_horizontal"] or meta["clean_coexist_dids"]:
        all_dids = mal_dids + meta["clean_coexist_dids"]
        for did in all_dids:
            ideal_h = ideal["ideal_horiz"].get(did, {})
            ideal_hv = ideal_h.get("overall_verdict", "clean")
            ideal_pos = _is_positive(ideal_hv)

            if mode == "dry":
                triggered = did in ideal["ideal_horiz"]  # 理想里有横向报告=应触发
                llm_hv = ideal_hv
                llm_pos = ideal_pos
            else:
                triggered = did in (llm_res.triggered_horiz if llm_res else set())
                llm_h = llm_res.horiz.get(did, {}) if llm_res else {}
                llm_hv = llm_h.get("overall_verdict", "clean")
                llm_pos = _is_positive(llm_hv)

            if ideal_pos and llm_pos:
                m.horiz_tp += 1
            elif ideal_pos and not llm_pos:
                m.horiz_fn += 1
            elif not ideal_pos and llm_pos:
                m.horiz_fp += 1
            else:
                m.horiz_tn += 1

            m.details.append({"sid": sid, "did": did.split(":")[-1], "type": "horiz",
                              "ideal": ideal_hv, "llm": llm_hv, "triggered": triggered,
                              "ok": (ideal_pos == llm_pos)})

    # 边界级：阈值合规（b01 不应触发，b02/b03 应触发）
    if meta["category"] == "boundary":
        m.threshold_total += 1
        should = meta["should_trigger_horizontal"]
        if mode == "dry":
            actual = should  # 理想自测
        else:
            # 恶意 DID 实际是否触发了横向
            actual = bool(mal_dids) and (mal_dids[0] in (llm_res.triggered_horiz if llm_res else set()))
        if should == actual:
            m.threshold_compliant += 1

    # 归因级：多 agent 场景，恶意 DID 应检出、干净 DID 应判 clean
    if meta["clean_coexist_dids"]:
        m.attribution_total += 1
        # 恶意 DID 检出 + 所有共存干净 DID 判 clean
        if mode == "dry":
            mal_ok = True
            clean_ok = all(not _is_positive(ideal["ideal_horiz"].get(d, {}).get("overall_verdict", "clean"))
                           for d in meta["clean_coexist_dids"])
        else:
            mal_ok = any(_is_positive(llm_res.horiz.get(d, {}).get("overall_verdict", "clean"))
                         for d in mal_dids) if llm_res else False
            clean_ok = all(not _is_positive(llm_res.horiz.get(d, {}).get("overall_verdict", "clean"))
                           for d in meta["clean_coexist_dids"]) if llm_res else False
        if mal_ok and clean_ok:
            m.attribution_correct += 1

    return m


def _verdict_dir_match(a: str, b: str) -> bool:
    return (_is_positive(a) == _is_positive(b)) or (a == "clean" and b == "clean")


def aggregate(metrics_by_sid: dict[str, Metrics]) -> dict:
    """汇总所有场景的指标。"""
    agg = Metrics()
    for m in metrics_by_sid.values():
        agg.vert_tp += m.vert_tp; agg.vert_fp += m.vert_fp
        agg.vert_fn += m.vert_fn; agg.vert_tn += m.vert_tn
        agg.horiz_tp += m.horiz_tp; agg.horiz_fp += m.horiz_fp
        agg.horiz_fn += m.horiz_fn; agg.horiz_tn += m.horiz_tn
        agg.score_diffs += m.score_diffs
        agg.direction_match += m.direction_match; agg.direction_total += m.direction_total
        agg.evidence_hits += m.evidence_hits
        agg.attribution_correct += m.attribution_correct; agg.attribution_total += m.attribution_total
        agg.threshold_compliant += m.threshold_compliant; agg.threshold_total += m.threshold_total

    def prec(tp, fp): return tp / (tp + fp) if (tp + fp) else 0.0
    def rec(tp, fn): return tp / (tp + fn) if (tp + fn) else 0.0
    def f1(p, r): return 2*p*r/(p+r) if (p+r) else 0.0

    vp, vr = prec(agg.vert_tp, agg.vert_fp), rec(agg.vert_tp, agg.vert_fn)
    hp, hr = prec(agg.horiz_tp, agg.horiz_fp), rec(agg.horiz_tp, agg.horiz_fn)
    vert_fpr = agg.vert_fp / (agg.vert_fp + agg.vert_tn) if (agg.vert_fp + agg.vert_tn) else 0.0
    horiz_fpr = agg.horiz_fp / (agg.horiz_fp + agg.horiz_tn) if (agg.horiz_fp + agg.horiz_tn) else 0.0

    return {
        "vertical": {"precision": vp, "recall": vr, "f1": f1(vp, vr),
                     "fpr": vert_fpr,
                     "tp": agg.vert_tp, "fp": agg.vert_fp, "fn": agg.vert_fn, "tn": agg.vert_tn},
        "horizontal": {"precision": hp, "recall": hr, "f1": f1(hp, hr),
                       "fpr": horiz_fpr,
                       "tp": agg.horiz_tp, "fp": agg.horiz_fp, "fn": agg.horiz_fn, "tn": agg.horiz_tn},
        "score_mae": sum(agg.score_diffs) / len(agg.score_diffs) if agg.score_diffs else 0.0,
        "direction_match_rate": agg.direction_match / agg.direction_total if agg.direction_total else 0.0,
        "evidence_hit_rate": sum(agg.evidence_hits) / len(agg.evidence_hits) if agg.evidence_hits else 0.0,
        "attribution_accuracy": agg.attribution_correct / agg.attribution_total if agg.attribution_total else None,
        "threshold_compliance": agg.threshold_compliant / agg.threshold_total if agg.threshold_total else None,
    }


# ── 报告输出 ─────────────────────────────────────────────────────────────────

def print_report(agg: dict, mode: str, n_scenarios: int, wall_time: float, details: list) -> None:
    print("\n" + "=" * 80)
    print(f"  ATTP Taint Analysis Benchmark — {mode.upper()} Mode Report")
    print("=" * 80)
    print(f"  Scenarios evaluated: {n_scenarios}  |  Wall time: {wall_time:.1f}s")

    v, h = agg["vertical"], agg["horizontal"]
    print(f"\n{'─'*80}")
    print("  VERTICAL (per-session detection)")
    print(f"{'─'*80}")
    print(f"  Precision: {v['precision']:.3f}    Recall: {v['recall']:.3f}    F1: {v['f1']:.3f}")
    print(f"  False Positive Rate: {v['fpr']:.3f}   (误报率 — 干净场景被误判比例)")
    print(f"  Confusion: TP={v['tp']} FP={v['fp']} FN={v['fn']} TN={v['tn']}")

    print(f"\n{'─'*80}")
    print("  HORIZONTAL (cross-session DID detection)")
    print(f"{'─'*80}")
    print(f"  Precision: {h['precision']:.3f}    Recall: {h['recall']:.3f}    F1: {h['f1']:.3f}")
    print(f"  False Positive Rate: {h['fpr']:.3f}")
    print(f"  Confusion: TP={h['tp']} FP={h['fp']} FN={h['fn']} TN={h['tn']}")

    print(f"\n{'─'*80}")
    print("  CALIBRATION & EVIDENCE")
    print(f"{'─'*80}")
    print(f"  Score MAE:                {agg['score_mae']:.3f}    (评分平均绝对误差, 越低越好)")
    print(f"  Direction Match Rate:     {agg['direction_match_rate']:.3f}    (判定方向一致比例)")
    print(f"  Evidence Trace Hit Rate:  {agg['evidence_hit_rate']:.3f}    (证据定位准确度)")

    if agg["attribution_accuracy"] is not None:
        print(f"\n{'─'*80}")
        print("  ATTRIBUTION (multi-agent)")
        print(f"{'─'*80}")
        print(f"  Attribution Accuracy:     {agg['attribution_accuracy']:.3f}    (锁定真凶且不误伤干净agent)")

    if agg["threshold_compliance"] is not None:
        print(f"\n{'─'*80}")
        print("  THRESHOLD BOUNDARY")
        print(f"{'─'*80}")
        print(f"  Threshold Compliance:     {agg['threshold_compliance']:.3f}    (b01不触发 + b02/b03触发)")

    print(f"\n{'─'*80}")
    print("  PER-SCENARIO DETAIL (misses only)")
    print(f"{'─'*80}")
    misses = [d for d in details if not d["ok"]]
    if not misses:
        print("  (none — all judgments correct)")
    else:
        for d in misses:
            tag = d.get("session") or d.get("did")
            print(f"  [{d['sid']}] {d['type']:<6} {tag:<14} ideal={d['ideal']:<10} llm={d['llm']:<10}"
                  + (f" triggered={d.get('triggered')}" if "triggered" in d else ""))
    print("=" * 80)


# ── Main ─────────────────────────────────────────────────────────────────────

def load_llm_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config not found: {CONFIG_PATH}"); sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    a = data.get("analysis", {})
    return {"api_key": a.get("apiKey") or a.get("api_key", ""),
            "base_url": a.get("baseUrl") or a.get("base_url", "https://api.openai.com/v1"),
            "model": a.get("model", "gpt-4o")}


def load_llm_result_from_db(sid: str) -> LLMResult:
    """从已有的 {sid}_llm.db 结果库重建 LLMResult（eval-only 模式用）。"""
    res = LLMResult(sid=sid)
    db_path = RESULTS_DIR / f"{sid}_llm.db"
    if not db_path.exists():
        res.error = f"result db not found: {db_path}"
        return res
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    for row in conn.execute("SELECT session_id, report_json FROM vertical_analysis_reports ORDER BY session_id, batch_index"):
        res.vert[row["session_id"]] = json.loads(row["report_json"])
    for row in conn.execute("SELECT did, report_json FROM horizontal_analysis_reports"):
        rpt = json.loads(row["report_json"])
        # 只把判定非 clean 的算作"触发检出"；clean 报告也算触发（横向确实运行了）
        res.horiz[row["did"]] = rpt
        res.triggered_horiz.add(row["did"])
    conn.close()
    return res


def run_eval_only_mode(scenario_filter: list[str] | None):
    """复用已生成的 {sid}_llm.db，不调 LLM，仅重算指标（用于 harness 修复后快速重评）。"""
    files = all_scenario_files(scenario_filter)
    print(f"  Scenarios: {len(files)} (eval-only, reusing existing LLM result DBs)")
    t0 = time.time()
    metrics_by_sid = {}
    details = []
    n_missing = 0
    for sid, dbp in files:
        ideal = load_ideal(dbp)
        llm_res = load_llm_result_from_db(sid)
        if llm_res.error:
            n_missing += 1
            print(f"  [skip] {sid}: {llm_res.error}")
            continue
        m = evaluate_one(sid, llm_res, ideal, mode="llm")
        metrics_by_sid[sid] = m
        details.extend(m.details)
    wall = time.time() - t0
    agg = aggregate(metrics_by_sid)
    print_report(agg, "eval-only", len(files) - n_missing, wall, details)
    if n_missing:
        print(f"\n  [!] {n_missing} scenario(s) had no result DB — run --mode llm first.")
    out = RESULTS_DIR / "eval_only_report.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"mode": "eval-only", "n_scenarios": len(files) - n_missing,
                   "metrics": agg, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"  Report saved: {out}")


async def run_llm_mode(scenario_filter: list[str] | None, concurrency: int = 8):
    llm_config = load_llm_config()
    if not llm_config["api_key"]:
        print("[ERROR] no API key"); sys.exit(1)
    RESULTS_DIR.mkdir(exist_ok=True)
    client = AsyncOpenAI(api_key=llm_config["api_key"], base_url=llm_config["base_url"])
    print(f"  LLM: {llm_config['model']} @ {llm_config['base_url']}")

    files = all_scenario_files(scenario_filter)
    print(f"  Scenarios: {len(files)} (concurrent, max_parallel={concurrency})")

    sem = asyncio.Semaphore(concurrency)
    t0 = time.time()
    tasks = [run_scenario_llm(sid, dbp, llm_config, client, sem) for sid, dbp in files]
    results = await asyncio.gather(*tasks)
    wall = time.time() - t0
    print(f"  Wall time: {wall:.1f}s")

    # 评估
    metrics_by_sid = {}
    details = []
    for (sid, dbp), res in zip(files, results):
        ideal = load_ideal(dbp)
        m = evaluate_one(sid, res, ideal, mode="llm")
        metrics_by_sid[sid] = m
        details.extend(m.details)
        if res.error:
            print(f"  [!] {sid} error: {res.error}")

    agg = aggregate(metrics_by_sid)
    print_report(agg, "llm", len(files), wall, details)

    # 保存结果
    out = RESULTS_DIR / "llm_eval_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"mode": "llm", "n_scenarios": len(files), "wall_time": wall,
                   "metrics": agg, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"\n  Report saved: {out}")


def run_dry_mode(scenario_filter: list[str] | None):
    """干跑：用理想数据自测评测逻辑。期望全部指标完美（1.0 / MAE=0）。"""
    files = all_scenario_files(scenario_filter)
    print(f"  Scenarios: {len(files)} (dry-run self-check)")
    t0 = time.time()
    metrics_by_sid = {}
    details = []
    for sid, dbp in files:
        ideal = load_ideal(dbp)
        m = evaluate_one(sid, None, ideal, mode="dry")
        metrics_by_sid[sid] = m
        details.extend(m.details)
    wall = time.time() - t0
    agg = aggregate(metrics_by_sid)
    print_report(agg, "dry", len(files), wall, details)
    print("\n  注: dry-run 用理想数据自测，期望 Precision/Recall/F1=1.0, MAE=0, Hit=1.0。")
    print("      若不为 1.0，说明评测逻辑或标注有 bug。")

    out = RESULTS_DIR / "dry_eval_report.json"
    RESULTS_DIR.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"mode": "dry", "n_scenarios": len(files),
                   "metrics": agg, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"  Report saved: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["dry", "llm", "eval-only"], default="dry",
                    help="dry=不调LLM自测逻辑; llm=真实LLM评测; eval-only=复用已有LLM结果DB重评")
    ap.add_argument("--scenarios", default="",
                    help="逗号分隔的 sid 列表，如 v01,h01,c08；空=全部")
    ap.add_argument("--concurrency", type=int, default=8,
                    help="LLM 模式最大并发场景数（防限流）")
    args = ap.parse_args()

    print("=" * 80)
    print(f"  ATTP Taint Analysis Benchmark Evaluator — {args.mode} mode")
    print("=" * 80)

    sf = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    if args.mode == "dry":
        run_dry_mode(sf)
    elif args.mode == "eval-only":
        run_eval_only_mode(sf)
    else:
        asyncio.run(run_llm_mode(sf, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
