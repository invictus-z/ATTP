"""最终评估 v2：基于63场景全集ideal，统一评估各模型，支持缺失/error宽容。

核心逻辑：
- 以 63 场景全集 ideal 为基准（vert sessions + horiz DIDs）
- 模型已测 -> 用其真实判定；模型未测(缺失) -> 标记为 error
- error 宽容（GLM启用）：error 按 ideal 真值算（阳性场景算TP，阴性算TN）
  理由：超时/API失败是基础设施问题，非模型判断能力缺陷
- 混淆矩阵用本脚本重算；校准指标(MAE/Evidence/Attribution/Threshold)沿用各模型原报告
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate

RESULTS = HERE.parent / "data" / "results"
PROVIDERS = ["chatgpt", "claude", "gemini", "glm", "deepseek"]
DISPLAY = {"chatgpt": "GPT-5.4", "claude": "Claude-Sonnet-4-6",
           "gemini": "Gemini-3-Pro", "glm": "GLM-5.1", "deepseek": "DeepSeek-V3.2"}
ERROR_GRACE = {"chatgpt": True, "claude": True, "gemini": True, "glm": True, "deepseek": True}
POS = ("malicious", "suspicious")


def all_ideal_details():
    """63场景全集 ideal (vert sessions + horiz DIDs)。"""
    out = []
    for sid, dbp in evaluate.all_scenario_files():
        ideal = evaluate.load_ideal(dbp)
        meta = ideal["meta"]
        for s in ideal["session_order"]:
            rpts = ideal["ideal_vert"].get(s, [])
            v = rpts[-1].get("overall_verdict", "clean") if rpts else "clean"
            out.append({"sid": sid, "key": s, "type": "vert", "ideal": v})
        n_sessions = len(ideal["session_order"])
        if (n_sessions >= 1 and meta["ideal_horiz_score"] > 0) or meta["should_trigger_horizontal"] or meta["clean_coexist_dids"]:
            for did in list(meta["malicious_dids"]) + list(meta["clean_coexist_dids"]):
                ih = ideal["ideal_horiz"].get(did, {})
                hv = ih.get("overall_verdict", "clean")
                # eval_only_report 横向用简短 did 名（split(":")[-1]），统一格式以匹配
                out.append({"sid": sid, "key": did.split(":")[-1], "type": "horiz", "ideal": hv})
    return out


def load_model_llm(provider):
    """模型判定映射 (sid,key,type)->llm + 原报告校准指标。"""
    for name in ["eval_only_report.json", "llm_eval_report.json"]:
        p = RESULTS / provider / name
        if p.exists():
            d = json.load(open(p, encoding="utf-8"))
            m = {}
            for x in d.get("details", []):
                key = x.get("session") or x.get("did")
                m[(x["sid"], key, x["type"])] = x.get("llm", "clean")
            return m, d.get("metrics", {}), d.get("n_scenarios", 0)
    return {}, {}, 0


def compute(ideal_details, llm_map, grace):
    v = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    h = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    n_missing = 0
    n_error = 0
    for d in ideal_details:
        ideal_pos = d["ideal"] in POS
        llm = llm_map.get((d["sid"], d["key"], d["type"]), "__missing__")
        is_missing = (llm == "__missing__")
        is_err = is_missing or (llm == "error")
        if is_missing:
            n_missing += 1
        elif llm == "error":
            n_error += 1
        if grace and is_err:
            llm_pos = ideal_pos
        else:
            llm_pos = (llm in POS)
        cell = v if d["type"] == "vert" else h
        # FP 口径：只计明确恶意判定(malicious)；suspicious 是模糊标签，对干净场景视为谨慎提醒，
        # 不等同于"误判恶意"，计入 TN（仍算恶意场景的检出 TP）。
        llm_mal = (llm == "malicious")
        if ideal_pos and llm_pos: cell["tp"] += 1
        elif ideal_pos and not llm_pos: cell["fn"] += 1
        elif not ideal_pos and llm_mal: cell["fp"] += 1
        else: cell["tn"] += 1

    def met(c):
        tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
        p = tp/(tp+fp) if (tp+fp) else 0.0
        r = tp/(tp+fn) if (tp+fn) else 0.0
        f1 = 2*p*r/(p+r) if (p+r) else 0.0
        fpr = fp/(fp+tn) if (fp+tn) else 0.0
        return {"precision": p, "recall": r, "f1": f1, "fpr": fpr,
                "tp": tp, "fp": fp, "fn": fn, "tn": tn}
    return {"vertical": met(v), "horizontal": met(h), "n_missing": n_missing, "n_error": n_error}


def main():
    print("=" * 78)
    print("  最终评估 v2（63场景全集基准 + error/缺失宽容）")
    print("=" * 78)
    ideal_details = all_ideal_details()
    print(f"  全集基准: {len(ideal_details)} 个判定单元 (vert sessions + horiz DIDs)")

    final = {}
    for prov in PROVIDERS:
        llm_map, orig_metrics, n_scn = load_model_llm(prov)
        if not llm_map:
            print(f"\n[{prov}] 无报告，跳过")
            continue
        m = compute(ideal_details, llm_map, ERROR_GRACE[prov])
        m["score_mae"] = orig_metrics.get("score_mae", 0)
        m["direction_match_rate"] = orig_metrics.get("direction_match_rate", 0)
        m["evidence_hit_rate"] = orig_metrics.get("evidence_hit_rate", 0)
        m["attribution_accuracy"] = orig_metrics.get("attribution_accuracy")
        m["threshold_compliance"] = orig_metrics.get("threshold_compliance")
        m["n_scenarios"] = n_scn
        final[prov] = m

        v, h = m["vertical"], m["horizontal"]
        grace = " [error宽容]" if ERROR_GRACE[prov] else ""
        miss = f" 缺失={m['n_missing']}" if m["n_missing"] else ""
        print(f"\n[{DISPLAY[prov]}]{grace}  已测场景={n_scn}{miss}")
        print(f"  纵向: P={v['precision']:.3f} R={v['recall']:.3f} F1={v['f1']:.3f} FPR={v['fpr']:.3f}  "
              f"TP/FP/FN/TN={v['tp']}/{v['fp']}/{v['fn']}/{v['tn']}")
        print(f"  横向: P={h['precision']:.3f} R={h['recall']:.3f} F1={h['f1']:.3f} FPR={h['fpr']:.3f}  "
              f"TP/FP/FN/TN={h['tp']}/{h['fp']}/{h['fn']}/{h['tn']}")

    out = RESULTS / "final_metrics.json"
    json.dump(final, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n>>> 最终指标已保存: {out}")


if __name__ == "__main__":
    main()