"""结构层防御测试 — 全分支覆盖的七步验证流水线注入测试。

按 protocol-node-verifylogic.md 的判定决策树，枚举全部判定分支为独立变体，
每变体注入受控样本，验证两点：
  (1) 检出：攻击变体应被通报（report 非空）、良性/不通报变体应被放行（None）；
  (2) 归因：攻击变体通报的 evidence_type 应与预期违规类型一致。

无需网络/大模型：内存 DID 解析器注入公钥，直接驱动 MaliciousNodeDetector。
产出：data/results/structural_defense_report.json + stdout 汇总。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "python"))

from cryptography.hazmat.primitives.asymmetric import ed25519  # noqa: E402

from attp.core.authentication.did_resolver import DIDResolutionResult  # noqa: E402
from attp.core.authentication.signatures import sign_hash  # noqa: E402
from attp.core.message.event import BackMessage, RecordedHop  # noqa: E402
from attp.core.sessions.protocol_node.pending_message import PendingMessage  # noqa: E402
from attp.protocol_node.engine.malicious_detector import EvidenceType, MaliciousNodeDetector  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "data" / "results"
TS_BASE = 1_700_000_000.0
K_PER = 31
NODE_TYPES = ("agent", "tool", "user")

EV = EvidenceType


# ── 内存 DID 解析器 ────────────────────────────────────────────────────────
class InMemoryDIDResolver:
    def __init__(self):
        self._keys: dict[str, object] = {}

    def register(self, did, pub):
        self._keys[did] = pub

    async def resolve_full(self, did, key_fragment="key-1"):
        return DIDResolutionResult(public_key=self._keys.get(did))


class MockSession:
    def __init__(self, trusted, subsequent=False, diff_identity=False):
        self._trusted = list(trusted)
        self._subsequent = subsequent
        self._diff = diff_identity

    def get_trusted_did_list(self):
        return self._trusted

    def get_latest_trusted_did(self):
        return self._trusted[-1] if self._trusted else ""

    def has_subsequent_activity_after(self, nonce):
        return self._subsequent

    def has_subsequent_with_different_verified_identity(self, nonce, node_did):
        return self._diff


@dataclass
class Node:
    did: str
    priv: object
    pub: object
    ntype: str


_counter = 0


def gen_node(role, resolver, ntype=None):
    global _counter
    _counter += 1
    priv = ed25519.Ed25519PrivateKey.generate()
    pub = priv.public_key()
    did = f"did:wba:pn.test:{role}_{_counter}"
    resolver.register(did, pub)
    return Node(did, priv, pub, ntype or random.choice(NODE_TYPES))


def hop_hash(session_id, sender_did, target_did, content, ts, hop_count):
    raw = json.dumps({
        "session_id": session_id, "sender_did": sender_did, "target_did": target_did,
        "content": content, "timestamp": ts, "hop_count": hop_count,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_pending(sender, target_did, content, nonce, sid, ts, ntype,
                 identity_verified=True, content_sig=None, node_did=None):
    chash = hop_hash(sid, sender.did, target_did, content, ts, [1, 0])
    sig = content_sig if content_sig is not None else sign_hash(chash, sender.priv)
    hop = {
        "session_id": sid, "sender_did": sender.did, "target_did": target_did,
        "Content": content, "Timestamp": ts, "Hop_Count": [1, 0], "Signature": sig,
    }
    return PendingMessage(
        hop=hop, session_id=sid, protocol_node_address="pn",
        sender_did=sender.did, sender_node_type=ntype,
        nonce=nonce, stored_at=time.time(),
        node_did=node_did or sender.did, identity_verified=identity_verified,
        identity_verification_attempted=True,
    )


def make_back(node, sender, target_did, content, nonce, sid, ts,
              identity_valid=True, sig_content=None):
    rh = RecordedHop(sid, sender.did, target_did, content, ts, [1, 0])
    rh.sig_content = sign_hash(rh.content_hash(), sender.priv) if sig_content is None else sig_content
    bm = BackMessage(protocol_url="pn", node_did=node.did, nonce=nonce, sig_identity="", recorded_hop=rh)
    bm.sign_identity(node.priv) if identity_valid else setattr(bm, "sig_identity", "invalidsig==")
    return bm


# ── 变体定义 ───────────────────────────────────────────────────────────────
# (key, 类别, kind, is_attack, expected_evidence, builder)
def variants():
    out = []

    def b_id_bp1_bad(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"a1_{i}", f"na1_{i}", TS_BASE + i
        # 回传1 身份签名无效在 Step 0a 即拦截；back2 仅需存在以供读取 node_did
        return (make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype, identity_verified=False),
                make_back(R, S, R.did, f"c{i}", n, sid, ts), MockSession([S.did]))

    def b_id_bp2_bad(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"a2_{i}", f"na2_{i}", TS_BASE + i
        return (make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype),
                make_back(R, S, R.did, f"c{i}", n, sid, ts, identity_valid=False),
                MockSession([S.did]))

    def b_id_trusted(r, i):
        S, R, X = gen_node("S", r), gen_node("R", r), gen_node("X", r)
        sid, n, ts = f"a3_{i}", f"na3_{i}", TS_BASE + i
        # 回传1 身份有效但 DID 不在可信名单
        return (make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype, identity_verified=True),
                make_back(R, S, R.did, f"c{i}", n, sid, ts), MockSession([X.did]))

    def b_id_same_did(r, i):
        M = gen_node("M", r)
        sid, n, ts = f"a4_{i}", f"na4_{i}", TS_BASE + i
        return (make_pending(M, M.did, f"c{i}", n, sid, ts, M.ntype, node_did=M.did),
                make_back(M, M, M.did, f"c{i}", n, sid, ts), MockSession([M.did]))

    def b_single_trusted(r, i):
        S, X = gen_node("S", r), gen_node("X", r)
        sid, n, ts = f"a5_{i}", f"na5_{i}", TS_BASE + i
        # 单回传 身份有效但 DID 不在可信名单
        return (make_pending(S, X.did, f"c{i}", n, sid, ts, S.ntype, identity_verified=True),
                None, MockSession([X.did]))

    def b_ct_bp1_bad(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"c1_{i}", f"nc1_{i}", TS_BASE + 1000 + i
        return (make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype, content_sig="badsig=="),
                make_back(R, S, R.did, f"c{i}", n, sid, ts), MockSession([S.did]))

    def b_ct_bp2_tampered(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"c2_{i}", f"nc2_{i}", TS_BASE + 1000 + i
        rh = RecordedHop(sid, S.did, R.did, f"c{i}", ts, [1, 0])
        return (make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype),
                make_back(R, S, R.did, f"c{i}", n, sid, ts, sig_content=sign_hash(rh.content_hash(), R.priv)),
                MockSession([S.did]))

    def b_ct_framing(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"c3_{i}", f"nc3_{i}", TS_BASE + 1000 + i
        # 发送方分别签署正常内容(给协议节点)与恶意指令(给接收方)
        return (make_pending(S, R.did, "normal-report", n, sid, ts, S.ntype),
                make_back(R, S, R.did, "malicious:exfil-key", n, sid, ts),
                MockSession([S.did]))

    def b_refuse(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"r1_{i}", f"nr1_{i}", TS_BASE + 2000 + i
        return (make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype),
                None, MockSession([S.did], subsequent=True, diff_identity=True))

    def b_benign_dual(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        coord = gen_node("K", r)
        sid, n, ts = f"b1_{i}", f"nb1_{i}", TS_BASE + 3000 + i
        content = f"benign-{i}"
        return (make_pending(S, R.did, content, n, sid, ts, S.ntype),
                make_back(R, S, R.did, content, n, sid, ts),
                MockSession([coord.did, S.did]))  # 多节点可信名单

    def b_benign_single(r, i):
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"b2_{i}", f"nb2_{i}", TS_BASE + 4000 + i
        return (make_pending(S, R.did, f"single-{i}", n, sid, ts, S.ntype),
                None, MockSession([S.did], subsequent=False))

    def b_garbage_single(r, i):
        # 单回传 身份签名无效 → 按设计丢弃（不通报）
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"b3_{i}", f"nb3_{i}", TS_BASE + 5000 + i
        return (make_pending(S, R.did, f"spam-{i}", n, sid, ts, S.ntype, identity_verified=False),
                None, MockSession([S.did]))

    def b_self_discard(r, i):
        # 单回传 身份有效+在名单，有后续活动但无不同身份 → 自发自弃，不通报
        S, R = gen_node("S", r), gen_node("R", r)
        sid, n, ts = f"b4_{i}", f"nb4_{i}", TS_BASE + 6000 + i
        return (make_pending(S, R.did, f"self-{i}", n, sid, ts, S.ntype),
                None, MockSession([S.did], subsequent=True, diff_identity=False))

    out.append(("回传1身份签名无效",   "身份伪造",       "dual",   True,  EV.IDENTITY_TAMPERING,     b_id_bp1_bad))
    out.append(("回传2身份签名无效",   "身份伪造",       "dual",   True,  EV.IDENTITY_TAMPERING,     b_id_bp2_bad))
    out.append(("可信名单违规(双)",    "身份伪造",       "dual",   True,  EV.TRUSTED_LIST_VIOLATION, b_id_trusted))
    out.append(("同一DID冒充双角色",   "身份伪造",       "dual",   True,  EV.SAME_DID_DUPLICATE,     b_id_same_did))
    out.append(("可信名单违规(单)",    "身份伪造",       "single", True,  EV.TRUSTED_LIST_VIOLATION, b_single_trusted))
    out.append(("回传1内容签名无效",   "内容篡改与栽赃", "dual",   True,  EV.CONTENT_TAMPERING,      b_ct_bp1_bad))
    out.append(("回传2内容被篡改",     "内容篡改与栽赃", "dual",   True,  EV.INDISTINGUISHABLE_PAIR, b_ct_bp2_tampered))
    out.append(("发送方双签栽赃",      "内容篡改与栽赃", "dual",   True,  EV.FRAMING,                b_ct_framing))
    out.append(("接收后拒绝回传",      "拒绝回传",       "single", True,  EV.NO_PROPAGATION,         b_refuse))
    out.append(("良性双回传",          "良性交互",       "dual",   False, None, b_benign_dual))
    out.append(("良性单回传",          "良性交互",       "single", False, None, b_benign_single))
    out.append(("垃圾单回传(按设计丢弃)", "按设计不通报", "single", False, None, b_garbage_single))
    out.append(("自发自弃(按设计丢弃)",  "按设计不通报", "single", False, None, b_self_discard))
    return out


async def run():
    random.seed(42)
    resolver = InMemoryDIDResolver()
    detector = MaliciousNodeDetector(resolver)
    vs = variants()

    per_var: list[dict] = []
    per_cat: dict[str, dict] = {}
    overall = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    cls_total = 0
    cls_correct = 0

    for key, cat, kind, is_attack, exp_ev, builder in vs:
        detected_n = 0
        cls_c = 0
        for i in range(K_PER):
            pending, back2, sess = builder(resolver, i)
            report = (await detector.evaluate_dual_back_prop(pending, back2, sess)
                      if kind == "dual"
                      else await detector.evaluate_single_back_prop(pending, sess))
            detected = report is not None
            if detected:
                detected_n += 1
            # 分类正确性（仅攻击变体）
            if is_attack:
                cls_total += 1
                ok = detected and report.evidence_type == exp_ev
                cls_c += int(ok)
                cls_correct += int(ok)

            c = per_cat.setdefault(cat, {"n": 0, "detected": 0})
            c["n"] += 1
            c["detected"] += int(detected)
            if is_attack:
                overall["tp" if detected else "fn"] += 1
            else:
                overall["fp" if detected else "tn"] += 1

        per_var.append({
            "variant": key, "category": cat, "is_attack": is_attack,
            "expected_evidence": exp_ev.value if exp_ev else None,
            "n": K_PER, "detected": detected_n,
            "detection_rate": round(detected_n / K_PER, 4),
            "classification_correct": cls_c,
            "classification_rate": round(cls_c / K_PER, 4),
        })

    tp, fp, fn, tn = overall["tp"], overall["fp"], overall["fn"], overall["tn"]
    detection_rate = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    f1 = 2 * precision * detection_rate / (precision + detection_rate) if (precision + detection_rate) else 0.0
    accuracy = (tp + tn) / (tp + fp + fn + tn)
    cls_rate = cls_correct / cls_total if cls_total else 0.0

    cat_rates = {c: {"n": v["n"], "detected": v["detected"],
                     "rate": round(v["detected"] / v["n"], 4) if v["n"] else 0.0}
                 for c, v in per_cat.items()}

    summary = {
        "n_per_variant": K_PER,
        "n_variants": len(vs),
        "per_variant": per_var,
        "per_category": cat_rates,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "detection_rate": round(detection_rate, 4),
        "fpr": round(fpr, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "classification_accuracy": round(cls_rate, 4),
    }
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / "structural_defense_report.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("  结构层防御测试结果（七步验证流水线 · 全分支覆盖）")
    print("=" * 72)
    print(f"  {len(vs)} 个变体 × {K_PER} 样本 = {len(vs)*K_PER} 条 "
          f"（攻击 {tp+fn} / 良性·不通报 {fp+tn}）")
    print("\n  变体级（检出 / 归因正确）：")
    for v in per_var:
        tag = "攻击" if v["is_attack"] else "放行"
        ev = f"→{v['expected_evidence']}" if v["is_attack"] else ""
        print(f"    [{tag}] {v['variant']:<22} 检出 {v['detected']}/{v['n']}"
              f"{(' 归因 ' + str(v['classification_correct']) + '/' + str(v['n'])) if v['is_attack'] else ''} {ev}")
    print(f"\n  各攻击类别检出率：")
    for c in ("身份伪造", "内容篡改与栽赃", "拒绝回传"):
        v = cat_rates[c]
        print(f"    {c:<12} {v['detected']}/{v['n']} = {v['rate']*100:.1f}%")
    benign = sum(per_cat.get(k, {"n": 0})["n"] for k in ("良性交互", "按设计不通报"))
    bfp = sum(per_cat.get(k, {"detected": 0})["detected"] for k in ("良性交互", "按设计不通报"))
    print(f"  良性·不通报误报：{bfp}/{benign} = {bfp/benign*100:.1f}%")
    print(f"\n  混淆矩阵  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  检出率={detection_rate*100:.1f}%  精确率={precision*100:.1f}%  "
          f"F1={f1*100:.1f}%  准确率={accuracy*100:.1f}%  FPR={fpr*100:.1f}%")
    print(f"  归因正确率（攻击证据类型分类）={cls_rate*100:.1f}%")
    print(f"\n>>> 已保存: {out}")
    return summary


if __name__ == "__main__":
    asyncio.run(run())
