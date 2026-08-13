"""RQ1-4 补做实验 — 公共件（隔离，只读现有 gemini 评测结果，输出到 data/results/rq/）。

口径（用户确认）：
- 主模型 gemini-3.1-flash-lite；R_T=7.0 / TAU_DEV=1.0 / R_S=200（三次方累计 cube@200，见 rq_rs_trigger_f1.json）。
- Macro-F1 = {偏离, 干净} 二类宏平均。
- Campaign = 节点级（DID）。攻击 campaign = malicious_dids；良性 campaign = 非 malicious 的 agent DID。
- 所有新 LLM 调用结果写入 data/results/rq/gemini/，不动现有 data/results/eval/。

只读来源：
- 场景 meta（malicious_dids / clean_coexist / hop_ideals）：test/benchmark/data/scenarios/{sid}_*.db
- 纵向 hop_scores / behavior_traces.content / vertical_analysis_states.intent：
  test/benchmark/data/results/eval/gemini/{sid}_llm.db（read-only）
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # intent_analysis/rq
BENCH_ROOT = HERE.parent.parent                  # test/benchmark
PROJECT_ROOT = BENCH_ROOT.parent.parent          # ATTP repo root
sys.path.insert(0, str(PROJECT_ROOT / "python"))
sys.path.insert(0, str(BENCH_ROOT))

from intent_analysis.runners import evaluate  # noqa: E402  (复用 load_ideal / all_scenario_files / load_llm_config)

# ── 常量 ────────────────────────────────────────────────────────────────────
MODEL = "gemini-3.1-flash-lite"
R_T = 7.0
TAU_DEV = 1.0
R_S = 200.0               # 横轴触发阈值（F=Σ sub-R_T s³ > R_S）；实验最佳 cube@200（F1=.933,P=1,FPR=0）
CORESET_M = 3             # coreset：每会话保留 top-M 高分跳
PERIODIC_FRAC = 0.4       # periodic：仅看按序最早 frac 的跳（模拟"定时审计早于攻击成熟"）

DATA = BENCH_ROOT / "data"
SCEN_DIR = DATA / "scenarios"
GEMINI_RES = DATA / "results" / "eval" / "gemini"   # 只读（评测主结果）
RQ_RES = DATA / "results" / "rq" / "gemini"          # 隔离输出
RQ_RES.mkdir(parents=True, exist_ok=True)


# ── 场景 / meta ─────────────────────────────────────────────────────────────
def scen_files(split: str):
    """返回 [(sid, scen_path, meta)]，跳过无 _benchmark_meta 的空壳 db，按 sid 去重。"""
    out, seen = [], set()
    for f in sorted(SCEN_DIR.glob("*.db")):
        sid = f.stem.split("_", 1)[0]
        c = sqlite3.connect(str(f))
        try:
            row = c.execute("SELECT value FROM _benchmark_meta WHERE key='spec'").fetchone()
        except sqlite3.OperationalError:
            c.close(); continue
        c.close()
        if not row or sid in seen:
            continue
        meta = json.loads(row[0])
        if meta.get("split") == split:
            out.append((sid, f, meta)); seen.add(sid)
    return out


def load_ideal(scen_path: Path) -> dict:
    return evaluate.load_ideal(scen_path)


def results_db(sid: str, root: Path | None = None) -> Path:
    return (root or GEMINI_RES) / f"{sid}_llm.db"


# ── 只读取数（gemini 结果库）────────────────────────────────────────────────
def load_did_hops(sid: str, root: Path | None = None) -> dict:
    """{did: [hop{trace_id,session_id,sender_did,field_type,score,severity,deviation_type}]}。"""
    db = results_db(sid, root)
    if not db.exists():
        return {}
    c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
    out: dict[str, list[dict]] = {}
    for r in c.execute(
        "SELECT trace_id,session_id,sender_did,field_type,score,severity,deviation_type "
        "FROM vertical_hop_scores"):
        out.setdefault(r["sender_did"], []).append(dict(r))
    c.close()
    return out


def load_content(sid: str, root: Path | None = None) -> dict:
    db = results_db(sid, root)
    if not db.exists():
        return {}
    c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
    out = {r["id"]: r["content"] for r in c.execute("SELECT id,content FROM behavior_traces")}
    c.close()
    return out


def load_intents(sid: str, max_trace_id: int | None = None, root: Path | None = None) -> dict:
    """{session_id: {goal,constraints,prohibitions}}，按 max_trace_id 截断（仿 orchestrator）。"""
    db = results_db(sid, root)
    if not db.exists():
        return {}
    c = sqlite3.connect(str(db)); c.row_factory = sqlite3.Row
    out = {}
    for r in c.execute("SELECT session_id, intent_revisions_json FROM vertical_analysis_states"):
        try:
            revs = json.loads(r["intent_revisions_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            revs = []
        if max_trace_id is not None:
            revs = [x for x in revs if (x.get("source") or {}).get("trace_id", 0) <= max_trace_id]
        out[r["session_id"]] = _accumulate_intent(revs)
    c.close()
    return out


def _accumulate_intent(revisions):
    goals, cons, proh = [], set(), set()
    for r in revisions or []:
        if r.get("goal"):
            goals.append(r["goal"])
        cons.update(r.get("constraints") or [])
        proh.update(r.get("prohibitions") or [])
    return {"goal": goals[-1] if goals else "",
            "constraints": sorted(cons), "prohibitions": sorted(proh)}


# ── confirm sessions_data 构造（仿 orchestrator._build_sessions_data）────────
def build_sessions_data(did_hops: list[dict], content: dict, intents: dict,
                        method: str, max_trace_id: int | None = None) -> list[dict]:
    """按方法裁剪 DID 的跳，构造 confirm 入参 sessions_data。

    - full      : 全部跳
    - coreset   : 每会话仅 top-M 高分跳（有界记忆）
    - periodic  : 仅按序最早的 PERIODIC_FRAC 跳（定时审计早于攻击成熟）
    """
    hops = sorted(did_hops, key=lambda x: x["trace_id"])
    if max_trace_id is not None:
        hops = [h for h in hops if h["trace_id"] <= max_trace_id]
    if method == "periodic":
        cut = max(1, int(len(hops) * PERIODIC_FRAC))
        hops = hops[:cut]

    per_sess: dict[str, list[dict]] = {}
    for h in hops:
        per_sess.setdefault(h["session_id"], []).append(h)

    sessions_data = []
    for sid, hs in per_sess.items():
        if method == "coreset":
            hs = sorted(hs, key=lambda x: x["score"], reverse=True)[:CORESET_M]
        hs_sorted = sorted(hs, key=lambda x: x["score"], reverse=True)
        hop_dicts = [{
            "trace_id": h["trace_id"], "score": h["score"], "severity": h["severity"],
            "deviation_type": h["deviation_type"], "field_type": h["field_type"],
            "content": content.get(h["trace_id"], ""),
        } for h in hs_sorted]
        w = sum(h["score"] ** 2 for h in hs_sorted)
        sessions_data.append({"session_id": sid, "w_value": w,
                              "intent": intents.get(sid, {}), "hops": hop_dicts})
    sessions_data.sort(key=lambda x: x["w_value"], reverse=True)
    return sessions_data


def f_accumulation(did_hops: list[dict]) -> float:
    """ATTP 触发信号 F = Σ_{s<=R_T} s³（三次方累计；轴职责分离：单跳 critical 交纵轴）。"""
    return sum(h["score"] ** 3 for h in did_hops if h["score"] <= R_T)


# ── 指标 ────────────────────────────────────────────────────────────────────
def macro_f1_binary(tp: int, fp: int, fn: int, tn: int) -> float:
    """{偏离(pos), 干净(neg)} 二类宏平均 F1。"""
    def f1(tp_, fp_, fn_):
        p = tp_ / (tp_ + fp_) if (tp_ + fp_) else 0.0
        r = tp_ / (tp_ + fn_) if (tp_ + fn_) else 0.0
        return 2 * p * r / (p + r) if (p + r) else 0.0
    return 0.5 * (f1(tp, fp, fn) + f1(tn, fn, fp))


def auprc(scores: list[float], labels: list[int]) -> float:
    """Average precision（PR 曲线下面积，按唯一阈值阶梯积分，tie 不变）。labels: 1=攻击。"""
    P = sum(labels)
    if P == 0:
        return 0.0
    ap = prev_recall = 0.0
    for thr in sorted(set(scores), reverse=True):
        retrieved = [y for s, y in zip(scores, labels) if s >= thr]
        tp = sum(retrieved); fp = len(retrieved) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / P
        ap += (recall - prev_recall) * precision
        prev_recall = recall
    return ap


def recall_at_fpr(scores: list[float], labels: list[int], fpr: float = 0.05) -> float:
    """攻击 campaign 召回 @ 良性 campaign FPR=fpr（threshold 取使良性误报率≤fpr 的最高分）。"""
    P = sum(labels); N = len(labels) - P
    if P == 0:
        return 0.0
    order = sorted(zip(scores, labels), key=lambda x: x[0], reverse=True)
    benign_allowed = N * fpr
    fp = tp = 0
    best = 0.0
    # 遍历阈值（按分降序纳入），保持 fp <= benign_allowed（允许 <=）时更新召回
    for s, y in order:
        if y == 1:
            tp += 1
        else:
            if fp + 1 > benign_allowed and fp >= benign_allowed:
                continue
            fp += 1
        best = max(best, tp / P)
    return best


def bootstrap_ci(diffs: list[float], n_boot: int = 2000, alpha: float = 0.05):
    """配对差的自助 95% CI + 双侧 p（H0: 均值=0）。返回 (mean, lo, hi, p)。

    无 numpy 依赖；用确定性索引（seed 固定）以可复现。
    """
    import random
    if not diffs:
        return (0.0, 0.0, 0.0, 1.0)
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(20260723)
    boot_means = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    lo = boot_means[int(n_boot * (alpha / 2))]
    hi = boot_means[min(n_boot - 1, int(n_boot * (1 - alpha / 2)))]
    # 双侧 p：|boot_mean - mean| 出现反向符号的比例
    ge = sum(1 for b in boot_means if b >= 0) / n_boot
    p = 2 * min(ge, 1 - ge)
    return (mean, lo, hi, p)


# ── LLM client ──────────────────────────────────────────────────────────────
def make_client():
    import os
    from openai import AsyncOpenAI
    cfg = evaluate.load_llm_config(MODEL)
    # 允许环境变量覆盖 api_key（不写入配置文件）
    key = os.environ.get("ATTP_RQ_API_KEY") or cfg["api_key"]
    return AsyncOpenAI(api_key=key, base_url=cfg["base_url"]), cfg["model"]


def save_json(name: str, obj):
    p = RQ_RES / name
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return p
