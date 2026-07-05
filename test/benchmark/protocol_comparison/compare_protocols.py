"""ATTP vs ANP/ACP/A2A 协议溯源能力对比 harness（按【会话】粒度）。

在同一批 63 个场景的全部 179 个会话上，比较三种协议下"用户侧能否定位恶意节点"：
  - ANP / ACP / A2A：用同一个取证审计 LLM(deepseek-v3.2)，在每个会话各自可见性 brief 下判断。
  - ATTP：复用已测的生产 Cross-Lock 纵向输出(data/results/deepseek/{sid}_llm.db，按 session_id)，不重跑。

评估单元为单个会话：攻击会话被检出=TP、漏报=FN；干净会话被误报=FP、正确判净=TN。
输出：data/results/protocol_comparison_report.json + 终端对比表。

运行:
  cd e:/work/ATTP
  python test/benchmark/protocol_comparison/compare_protocols.py
  python test/benchmark/protocol_comparison/compare_protocols.py --scenarios v01,h13,c01 --concurrency 8
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH_ROOT = HERE.parent                       # test/benchmark
SCENARIOS_DIR = BENCH_ROOT / "data" / "scenarios"
RESULTS_DIR = BENCH_ROOT / "data" / "results"

from forensic_audit import audit, make_client, load_config
from protocol_frontiers import ANP, ACP, A2A, ATTP, FRONTIERS, build_brief


# ── 数据加载（自包含，避免引入 evaluate.py 的重型 attp.core 依赖）──────────────

def _is_positive(verdict: str) -> bool:
    return verdict in ("malicious", "suspicious")


def _evidence_trace_ids(report: dict) -> set[int]:
    ids = set()
    for nv in report.get("node_verdicts", []):
        for ev in nv.get("evidence_items", []):
            ids.update(ev.get("trace_ids", []))
    return ids


def load_ideal(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    meta = json.loads(conn.execute("SELECT value FROM _benchmark_meta WHERE key='spec'").fetchone()["value"])
    sessions: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT * FROM behavior_traces ORDER BY id"):
        t = dict(row)
        sessions.setdefault(t["session_id"], []).append(t)
    ideal_vert: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT session_id, report_json FROM vertical_analysis_reports ORDER BY session_id, batch_index"):
        ideal_vert.setdefault(row["session_id"], []).append(json.loads(row["report_json"]))
    conn.close()
    return {"meta": meta, "sessions": sessions,
            "session_order": sorted(sessions.keys(), key=lambda s: sessions[s][0]["id"]),
            "ideal_vert": ideal_vert}


def all_scenario_files(scenario_filter: list[str] | None = None) -> list[tuple[str, Path]]:
    out = []
    for f in sorted(SCENARIOS_DIR.glob("*.db")):
        sid = f.stem[:3]
        if scenario_filter and sid not in scenario_filter:
            continue
        out.append((sid, f))
    return out


def _short(did: str) -> str:
    return did.split(":")[-1] if did else ""


def short_names(dids) -> set[str]:
    return {_short(d) for d in dids if d}


# ── Ground truth ──────────────────────────────────────────────────────────────

def scenario_has_attack(ideal: dict) -> bool:
    """场景是否含真实攻击：任一 session 的理想纵向报告为阳性且含证据 trace。"""
    for s, reports in ideal["ideal_vert"].items():
        for rpt in reports:
            if _is_positive(rpt.get("overall_verdict", "clean")) and _evidence_trace_ids(rpt):
                return True
    return False


def session_has_attack(ideal: dict, session_id: str) -> bool:
    """单个会话是否为攻击会话：该 session 的理想纵向报告为阳性且含证据 trace。"""
    for rpt in ideal["ideal_vert"].get(session_id, []):
        if _is_positive(rpt.get("overall_verdict", "clean")) and _evidence_trace_ids(rpt):
            return True
    return False


# ── ATTP 复用：从 {sid}_llm.db 读生产 Cross-Lock 输出 ──────────────────────────

def attp_reused_verdict(sid: str) -> tuple[bool | None, set[str], set[str]]:
    """复用生产 Cross-Lock 输出，返回 (detected, accused_agents, accused_tools)。

    accused 来源：vertical/horizontal 报告中 taint>=0.7 的 agent 节点 + malicious_reports 官方归因。
    ATTP 会标注完整恶意链路（真凶 + 中转 coordinator + 外泄工具），故 accused_agents 可能含 coordinator；
    归因判定以"是否命中真凶(malicious_dids)"为准——这正是 ATTP 的核心能力。

    结果库位置：优先 results/{sid}_llm.db（旧布局），回退 results/deepseek/{sid}_llm.db（provider 子目录布局）。
    """
    candidates = [RESULTS_DIR / f"{sid}_llm.db", RESULTS_DIR / "deepseek" / f"{sid}_llm.db"]
    dbp = next((p for p in candidates if p.exists()), None)
    if dbp is None:
        return None, set(), set()
    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    detected = False
    acc_agents: set[str] = set()
    acc_tools: set[str] = set()
    for row in conn.execute("SELECT report_json FROM vertical_analysis_reports"):
        rpt = json.loads(row["report_json"])
        if _is_positive(rpt.get("overall_verdict", "clean")):
            detected = True
        for nv in rpt.get("node_verdicts", []):
            did = nv.get("node_did", "")
            if float(nv.get("taint_score", 0.0)) >= 0.7 and ":agent:" in did:
                acc_agents.add(_short(did))
    for row in conn.execute("SELECT report_json FROM horizontal_analysis_reports"):
        rpt = json.loads(row["report_json"])
        if _is_positive(rpt.get("overall_verdict", "clean")):
            detected = True
            did = rpt.get("did_verdict", {}).get("did", "")
            if ":agent:" in did:
                acc_agents.add(_short(did))
    for row in conn.execute("SELECT target_did FROM malicious_reports"):
        did = row["target_did"]
        if ":agent:" in did:
            acc_agents.add(_short(did))
            detected = True  # 有恶意归因报告 → 视为检出
        elif ":tool:" in did:
            acc_tools.add(_short(did))
    conn.close()
    return detected, acc_agents, acc_tools


def attp_reused_session_verdict(sid: str, session_id: str) -> tuple[bool | None, set[str]]:
    """复用生产 Cross-Lock 输出，返回某会话是否被检出 + 被指认 agent 短名集合。

    结果库：results/deepseek/{sid}_llm.db。按 session_id 读取纵向报告，
    任一 batch 为阳性(malicious/suspicious)即视为该会话被检出。
    """
    dbp = RESULTS_DIR / "deepseek" / f"{sid}_llm.db"
    if not dbp.exists():
        return None, set()
    conn = sqlite3.connect(str(dbp))
    conn.row_factory = sqlite3.Row
    detected = False
    acc_agents: set[str] = set()
    for row in conn.execute(
        "SELECT report_json FROM vertical_analysis_reports WHERE session_id = ? ORDER BY batch_index",
        (session_id,),
    ):
        rpt = json.loads(row["report_json"])
        if _is_positive(rpt.get("overall_verdict", "clean")):
            detected = True
        for nv in rpt.get("node_verdicts", []):
            did = nv.get("node_did", "")
            if float(nv.get("taint_score", 0.0)) >= 0.7 and ":agent:" in did:
                acc_agents.add(_short(did))
    conn.close()
    return detected, acc_agents


# ── 评分 ──────────────────────────────────────────────────────────────────────

_NULL_NAMES = {"", "none", "null", "无", "未发现", "未知", "n/a", "na", "-"}


def accused_from_name(named_raw: str, candidates: set[str]) -> set[str]:
    """把 LLM 给出的恶意节点名映射到场景中真实 agent 短名（子串匹配，容忍全 DID/自然语言）。"""
    norm = (named_raw or "").strip().lower()
    if norm in _NULL_NAMES:
        return set()
    return {c for c in candidates if c.lower() in norm}


def score_frontier(detected: bool, accused: set[str], has_attack: bool, mal_set: set[str]) -> dict:
    """统一的场景级评分。accused=该前沿指认的 agent 短名集合。"""
    if has_attack:
        identified = bool(accused & mal_set)  # 是否命中至少一个真凶
        return {"detected": detected, "detection_correct": detected,
                "identified_attacker": detected and identified,
                "misattribution": detected and bool(accused) and not identified,
                "false_positive": False}
    else:  # clean 场景
        return {"detected": detected, "detection_correct": not detected,
                "identified_attacker": False, "misattribution": False,
                "false_positive": detected}


def aggregate(records: list[dict], frontiers=FRONTIERS + (ATTP,)) -> dict:
    out: dict[str, dict] = {}
    for fr in frontiers:
        atk = [r for r in records if r["has_attack"] and r[fr] is not None]
        cln = [r for r in records if not r["has_attack"] and r[fr] is not None]
        n_atk, n_cln = len(atk), len(cln)
        det = sum(1 for r in atk if r[fr]["detected"])
        attr = sum(1 for r in atk if r[fr]["identified_attacker"])
        mis = sum(1 for r in atk if r[fr]["misattribution"])
        fp = sum(1 for r in cln if r[fr]["false_positive"])
        out[fr] = {
            "detection_rate": det / n_atk if n_atk else None,
            "attribution_rate": attr / n_atk if n_atk else None,
            "misattribution_rate": mis / n_atk if n_atk else None,
            "fpr": fp / n_cln if n_cln else None,
            "n_attack": n_atk, "n_clean": n_cln,
        }
    return out


def group_aggregate(records: list[dict], key_fn) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(str(key_fn(r)), []).append(r)
    return {g: aggregate(recs) for g, recs in groups.items()}


def confusion_metrics(records: list[dict], frontiers=FRONTIERS + (ATTP,)) -> dict:
    """标准二分类混淆矩阵（是否攻击 × 是否检出）+ 派生指标。

    TP=攻击且检出  FN=攻击但漏报  FP=干净但误报  TN=干净且正确判净。
    派生：Precision/Recall/F1/Accuracy/FPR/Specificity。
    """
    out: dict[str, dict] = {}
    for fr in frontiers:
        rs = [r for r in records if r[fr] is not None]
        if not rs:
            out[fr] = None
            continue
        tp = sum(1 for r in rs if r["has_attack"] and r[fr]["detected"])
        fn = sum(1 for r in rs if r["has_attack"] and not r[fr]["detected"])
        fp = sum(1 for r in rs if not r["has_attack"] and r[fr]["detected"])
        tn = sum(1 for r in rs if not r["has_attack"] and not r[fr]["detected"])
        P = tp / (tp + fp) if (tp + fp) else 0.0
        R = tp / (tp + fn) if (tp + fn) else 0.0
        F1 = 2 * P * R / (P + R) if (P + R) else 0.0
        out[fr] = {
            "tp": tp, "fn": fn, "fp": fp, "tn": tn,
            "precision": P, "recall": R, "f1": F1,
            "accuracy": (tp + tn) / len(rs),
            "fpr": fp / (fp + tn) if (fp + tn) else 0.0,
            "specificity": tn / (tn + fp) if (tn + fp) else 0.0,
            "n": len(rs),
        }
    return out


def cm_group_aggregate(records: list[dict], key_fn) -> dict:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(str(key_fn(r)), []).append(r)
    return {g: confusion_metrics(recs) for g, recs in groups.items()}


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def run(scenario_filter: list[str] | None, concurrency: int) -> dict:
    cfg = load_config()
    client, model = make_client()
    files = all_scenario_files(scenario_filter)
    print("=" * 80)
    print(f"  协议溯源能力对比（按会话）— 取证审计 LLM: {model} @ {cfg['base_url']}")

    # 预载场景数据 + 统计会话数
    scene_data = []
    n_sessions = 0
    for sid, dbp in files:
        ideal = load_ideal(dbp)
        scene_data.append((sid, dbp, ideal))
        n_sessions += len(ideal["session_order"])
    print(f"  场景 {len(files)} / 会话 {n_sessions} × 前沿 {len(FRONTIERS)} = "
          f"{n_sessions * len(FRONTIERS)} 次审计调用 (ATTP 复用生产数据, 不调用)")
    print("=" * 80)

    sem = asyncio.Semaphore(concurrency)

    async def audit_one(sess_traces, meta, frontier):
        brief = build_brief(sess_traces, meta, frontier)
        async with sem:
            return await audit(brief, client, model)

    t0 = time.time()
    tasks = []
    keys = []
    for sid, dbp, ideal in scene_data:
        meta = ideal["meta"]
        for session_id in ideal["session_order"]:
            sess_traces = ideal["sessions"][session_id]
            for fr in FRONTIERS:
                tasks.append(audit_one(sess_traces, meta, fr))
                keys.append((sid, session_id, fr))
    raw_results = await asyncio.gather(*tasks)
    audit_by = {k: r for k, r in zip(keys, raw_results)}
    wall = time.time() - t0
    print(f"  取证审计完成，耗时 {wall:.1f}s")

    # 评分（每会话一条记录）
    records = []
    n_attp_missing = 0
    for sid, dbp, ideal in scene_data:
        meta = ideal["meta"]
        mal_set = short_names(meta["malicious_dids"])
        all_traces: list[dict] = []
        for s in ideal["session_order"]:
            all_traces.extend(ideal["sessions"][s])
        candidate_agents = short_names(
            {t["node_did"] for t in all_traces if ":agent:" in t["node_did"]} |
            {t["target"] for t in all_traces if ":agent:" in t.get("target", "")}
        ) | mal_set
        for session_id in ideal["session_order"]:
            has_attack = session_has_attack(ideal, session_id)
            rec: dict = {"sid": sid, "session_id": session_id, "name": meta["name"],
                         "category": meta["category"], "difficulty": meta["difficulty"],
                         "has_attack": has_attack, "malicious_dids": sorted(mal_set)}
            for fr in FRONTIERS:
                v = audit_by[(sid, session_id, fr)]
                accused = accused_from_name(v.get("malicious_did", ""), candidate_agents)
                rec[fr] = {"raw": v, **score_frontier(bool(v.get("detected")), accused, has_attack, mal_set)}
            det, ag = attp_reused_session_verdict(sid, session_id)
            if det is None:
                n_attp_missing += 1
                rec[ATTP] = None
            else:
                rec[ATTP] = {"detected": det, "accused_agents": sorted(ag),
                             **score_frontier(det, ag, has_attack, mal_set)}
            records.append(rec)

    if n_attp_missing:
        print(f"  [!] {n_attp_missing} 个会话缺少 {RESULTS_DIR}/deepseek/{{sid}}_llm.db —— ATTP 列将缺失")

    overall = aggregate(records)
    by_cat = group_aggregate(records, lambda r: r["category"])
    by_diff = group_aggregate(records, lambda r: r["difficulty"])
    cm_overall = confusion_metrics(records)
    cm_by_cat = cm_group_aggregate(records, lambda r: r["category"])

    attp_ref = load_attp_production_reference()

    report = {"model": model, "base_url": cfg["base_url"], "granularity": "session",
              "n_scenarios": len(files), "n_sessions": len(records),
              "wall_time": wall, "overall": overall, "by_category": by_cat,
              "by_difficulty": by_diff, "confusion_matrix": cm_overall,
              "confusion_matrix_by_category": cm_by_cat,
              "attp_production_reference": attp_ref, "details": records}
    return report


def load_attp_production_reference() -> dict:
    p = RESULTS_DIR / "llm_eval_report.json"
    if not p.exists():
        return {"note": f"未找到 {p}，请先跑 evaluate.py"}
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    m = data.get("metrics", {})
    return {
        "vertical_f1": m.get("vertical", {}).get("f1"),
        "vertical_precision": m.get("vertical", {}).get("precision"),
        "vertical_recall": m.get("vertical", {}).get("recall"),
        "vertical_fpr": m.get("vertical", {}).get("fpr"),
        "horizontal_f1": m.get("horizontal", {}).get("f1"),
        "attribution_accuracy": m.get("attribution_accuracy"),
        "source": "results/llm_eval_report.json (生产 Cross-Lock 实测, 复用)",
    }


def print_table(report: dict) -> None:
    print("\n" + "=" * 80)
    print("  协议溯源能力对比 — 标准混淆矩阵 (Overall)")
    print("=" * 80)
    cols = [ANP, ACP, A2A, ATTP]
    cm = report["confusion_matrix"]
    n_atk = sum(cm[c]["tp"] + cm[c]["fn"] for c in cols[:1])
    n_cln = sum(cm[c]["tn"] + cm[c]["fp"] for c in cols[:1])
    print(f"  真实\\预测        " + "".join(f"{c:>16}" for c in cols))
    print(f"  {'-' * (16 + 16 * len(cols))}")
    print(f"  {'实际=攻击':<14}" + "".join(f"{'TP='+str(cm[c]['tp']):>8}/FN="+str(cm[c]['fn']) for c in cols))
    print(f"  {'实际=干净':<14}" + "".join(f"{'FP='+str(cm[c]['fp']):>8}/TN="+str(cm[c]['tn']) for c in cols))

    print("\n  派生指标 (由混淆矩阵计算)")
    print(f"  {'-' * (16 + 16 * len(cols))}")
    rows = [("Precision  (TP/(TP+FP))", "precision"), ("Recall  (TP/(TP+FN))", "recall"),
            ("F1-score", "f1"), ("Accuracy", "accuracy"),
            ("FPR  (FP/(FP+TN))", "fpr"), ("Specificity (TN/(TN+FP))", "specificity")]
    pct = lambda x: "  n/a " if x is None else f"{x*100:6.1f}%"
    for label, key in rows:
        print(f"  {label:<22}" + "".join(f"{pct(cm[c][key]):>16}" for c in cols))

    print("\n  按类别 Recall (TP率):")
    for cat, agg in report["confusion_matrix_by_category"].items():
        parts = [f"{cat:<12}"]
        for c in cols:
            v = agg[c]
            parts.append(f"{c}={v['recall']*100:4.0f}%" if v else f"{c}=n/a")
        print("  " + "  ".join(parts))
    print("=" * 80)


def fmt(x):
    return "  -  " if x is None else f"{x*100:5.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="", help="逗号分隔 sid 列表，如 v01,h13；空=全部")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    sf = [s.strip() for s in args.scenarios.split(",") if s.strip()] or None
    report = asyncio.run(run(sf, concurrency=args.concurrency))

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / "protocol_comparison_report.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print_table(report)
    print(f"\n  对比数据已保存: {out}")

    # ── 合理性自检 ──
    # 核心断言：ATTP 显著优于所有基线；基线整体处于低检出区间(结构性接近失败)。
    # 三种非ATTP协议在"内部工具调用不可见"这一点上一致 → 都应低检出；彼此间小幅差异属LLM噪声。
    ov = report["overall"]
    warns = []
    attp_det = ov[ATTP]["detection_rate"]
    base_dets = [ov[f]["detection_rate"] for f in FRONTIERS if ov[f]["detection_rate"] is not None]
    if attp_det is not None and base_dets:
        max_base = max(base_dets)
        if attp_det - max_base < 0.30:
            warns.append(f"ATTP 优势不明显: ATTP={attp_det*100:.1f}% vs 基线最高={max_base*100:.1f}%")
        if max_base > 0.25:
            warns.append(f"基线检出偏高({max_base*100:.1f}%)——非ATTP协议应结构性接近失败(预期<25%)")
    if base_dets and all(d == 0.0 for d in base_dets):
        warns.append("所有基线检出率为干净0%——考虑适当丰富可见性 brief 后重跑")
    if warns:
        print("\n  [自检告警]")
        for w in warns:
            print(f"    - {w}")
    else:
        print("  [自检] 排序与基线非零检查通过。")


if __name__ == "__main__":
    main()
