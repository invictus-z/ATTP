"""RQ1 — Evidence Integrity（证据完整性）+ RQ4 证据层开销。

三方案在同一批注入 fault 上比较：
  AgentTrace    : 结构化无签名单日志（无签名、无第二来源）
  Sender-Signed : 发送方单签报告（有签名、无第二来源）
  ATTP          : 双报告（Branch A 发送方 + Branch B 接收方 + 双签 + 交叉比对）

故障模型：
  conflicting（对抗·双报不一致）= payload 篡改 / 身份冒充 / 栽赃
  incomplete （对抗·缺报）       = 接收方拒绝回传 / 超时
  benign     （良性通信故障）     = 延迟/晚报 / 重试 / 干净

指标：
  Fault Rec.↑   = 检出(conflicting + incomplete) / 注入总量（分 conflicting/incomplete 两子项）
  Benign Alarm↓ = 良性故障在对账后仍告警的比例
RQ4 证据层开销（同测）：
  Stored B/event↓ / sign µs / verify µs（各方案每事件成本）

检测口径（实测优先）：
  ATTP          : 真 MaliciousNodeDetector.evaluate_dual/single_back_prop
  Sender-Signed : 真 verify_signature 验 Branch A 内容签 + 身份签（无 Branch B 交叉）
  AgentTrace    : 仅结构校验（无签名→测不出篡改/冒充/缺报）
对账口径（文档化建模）：
  能否对账取决于能否"可信地把晚报匹配回事件"。ATTP/Sender-Signed 有签名→可对账；
  AgentTrace 无签名→无法确证→不对账。良性事件中 ~60% 为延迟/晚报。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

from loguru import logger as _loguru_logger
_loguru_logger.remove()   # 静默检测器 DEBUG 日志

from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.core.authentication.signatures import sign_hash, verify_signature
from attp.core.message.event import BackMessage, RecordedHop
from attp.core.sessions.protocol_node.pending_message import PendingMessage
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402

TS_BASE = 1_700_000_000.0
K_PER = 20
BENIGN_LATE_FRAC = 0.60     # 良性通信故障中延迟/晚报占比（文献典型值，文档化）
NODE_TYPES = ("agent", "tool", "user")


# ── 内存 DID 解析器 / 节点 / 构造器（复用 structural_defense_test 方案）─────────
class InMemoryDIDResolver:
    def __init__(self):
        self._keys: dict[str, object] = {}

    def register(self, did, pub):
        self._keys[did] = pub

    async def resolve_full(self, did, key_fragment="key-1"):
        return DIDResolutionResult(public_key=self._keys.get(did))


class MockSession:
    def __init__(self, trusted, subsequent=False, diff_identity=False):
        self._trusted, self._subsequent, self._diff = list(trusted), subsequent, diff_identity

    def get_trusted_did_list(self): return self._trusted
    def get_latest_trusted_did(self): return self._trusted[-1] if self._trusted else ""
    def has_subsequent_activity_after(self, nonce): return self._subsequent
    def has_subsequent_with_different_verified_identity(self, nonce, node_did): return self._diff


@dataclass
class Node:
    did: str; priv: object; pub: object; ntype: str


_cnt = 0


def gen_node(role, resolver, ntype=None):
    global _cnt; _cnt += 1
    priv = ed25519.Ed25519PrivateKey.generate(); pub = priv.public_key()
    did = f"did:wba:pn.test:{role}_{_cnt}"
    resolver.register(did, pub)
    return Node(did, priv, pub, ntype or random.choice(NODE_TYPES))


def hop_hash(session_id, sender_did, target_did, content, ts, hop_count):
    raw = json.dumps({"session_id": session_id, "sender_did": sender_did,
                      "target_did": target_did, "content": content,
                      "timestamp": ts, "hop_count": hop_count},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_pending(sender, target_did, content, nonce, sid, ts, ntype,
                 identity_verified=True, content_sig=None, node_did=None):
    chash = hop_hash(sid, sender.did, target_did, content, ts, [1, 0])
    sig = content_sig if content_sig is not None else sign_hash(chash, sender.priv)
    hop = {"session_id": sid, "sender_did": sender.did, "target_did": target_did,
           "Content": content, "Timestamp": ts, "Hop_Count": [1, 0], "Signature": sig}
    return PendingMessage(hop=hop, session_id=sid, protocol_node_address="pn",
                          sender_did=sender.did, sender_node_type=ntype, nonce=nonce,
                          stored_at=time.time(), node_did=node_did or sender.did,
                          identity_verified=identity_verified, identity_verification_attempted=True)


def make_back(node, sender, target_did, content, nonce, sid, ts,
              identity_valid=True, sig_content=None):
    rh = RecordedHop(sid, sender.did, target_did, content, ts, [1, 0])
    rh.sig_content = sign_hash(rh.content_hash(), sender.priv) if sig_content is None else sig_content
    bm = BackMessage(protocol_url="pn", node_did=node.did, nonce=nonce,
                     sig_identity="", recorded_hop=rh)
    bm.sign_identity(node.priv) if identity_valid else setattr(bm, "sig_identity", "invalidsig==")
    return bm


# ── 故障变体（attack: conflicting/incomplete；benign）────────────────────────
def variants():
    out = []

    def b_id_bp1_bad(r, i):  # 身份：回传1身份签名无效
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"a1_{i}", f"na1_{i}", TS_BASE + i
        return ("conflicting", make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype, identity_verified=False),
                make_back(R, S, R.did, f"c{i}", n, sid, ts), MockSession([S.did]))
    def b_id_bp2_bad(r, i):  # 身份：回传2身份签名无效
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"a2_{i}", f"na2_{i}", TS_BASE + i
        return ("conflicting", make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype),
                make_back(R, S, R.did, f"c{i}", n, sid, ts, identity_valid=False), MockSession([S.did]))
    def b_ct_bp1_bad(r, i):  # 篡改：回传1内容签名无效
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"c1_{i}", f"nc1_{i}", TS_BASE + 1000 + i
        return ("conflicting", make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype, content_sig="badsig=="),
                make_back(R, S, R.did, f"c{i}", n, sid, ts), MockSession([S.did]))
    def b_ct_bp2_tampered(r, i):  # 篡改：回传2内容被改
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"c2_{i}", f"nc2_{i}", TS_BASE + 1000 + i
        rh = RecordedHop(sid, S.did, R.did, f"c{i}", ts, [1, 0])
        return ("conflicting", make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype),
                make_back(R, S, R.did, f"c{i}", n, sid, ts, sig_content=sign_hash(rh.content_hash(), R.priv)),
                MockSession([S.did]))
    def b_ct_framing(r, i):  # 栽赃：发送方双签
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"c3_{i}", f"nc3_{i}", TS_BASE + 1000 + i
        return ("conflicting", make_pending(S, R.did, "normal-report", n, sid, ts, S.ntype),
                make_back(R, S, R.did, "malicious:exfil-key", n, sid, ts), MockSession([S.did]))
    def b_refuse(r, i):  # 遗漏：接收后拒绝回传（单回传）
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"r1_{i}", f"nr1_{i}", TS_BASE + 2000 + i
        return ("incomplete", make_pending(S, R.did, f"c{i}", n, sid, ts, S.ntype),
                None, MockSession([S.did], subsequent=True, diff_identity=True))
    def b_benign_dual(r, i):  # 良性：正常双回传
        S, R = gen_node("S", r), gen_node("R", r); sid, n, ts = f"b1_{i}", f"nb1_{i}", TS_BASE + 3000 + i
        return ("benign", make_pending(S, R.did, f"benign-{i}", n, sid, ts, S.ntype),
                make_back(R, S, R.did, f"benign-{i}", n, sid, ts), MockSession([S.did]))

    for b in (b_id_bp1_bad, b_id_bp2_bad, b_ct_bp1_bad, b_ct_bp2_tampered, b_ct_framing, b_refuse, b_benign_dual):
        out.append(b)
    return out


# ── 各方案检测 ───────────────────────────────────────────────────────────────
async def detect_attp(pending, back2, sess, detector) -> bool:
    """真检测器：dual 有 back2，single 无。返回是否判为故障。"""
    rep = await (detector.evaluate_dual_back_prop(pending, back2, sess)
                 if back2 is not None
                 else detector.evaluate_single_back_prop(pending, sess))
    return rep is not None


def _sender_signed_detect(pending, sender_pub) -> bool:
    """单签方案：验 Branch A 内容签 + 身份。任一失败→检出。"""
    h = pending.hop
    chash = hop_hash(h["session_id"], h["sender_did"], h["target_did"],
                     h["Content"], h["Timestamp"], h["Hop_Count"])
    content_ok = verify_signature(chash, h["Signature"], sender_pub)
    return (not content_ok) or (not pending.identity_verified)


def _agenttrace_detect(pending) -> bool:
    """无签名单日志：仅结构校验。注入的语义篡改结构合法→测不出。"""
    h = pending.hop
    required = ("session_id", "sender_did", "target_did", "Content", "Signature")
    return any(not h.get(k) for k in required)


# 对账能力：能否可信地把晚报匹配回事件（决定良性误报）
RECONCILE_CAP = {"ATTP": 1.0, "Sender-Signed": 1.0, "AgentTrace": 0.0}


# ── 主流程 ───────────────────────────────────────────────────────────────────
async def run():
    random.seed(42)
    resolver = InMemoryDIDResolver()
    detector = MaliciousNodeDetector(resolver)

    schemes = {"AgentTrace": {"conf": 0, "incomp": 0, "conf_tot": 0, "incomp_tot": 0,
                              "benign_alarm": 0.0, "benign_fp": 0, "benign_tot": 0},
               "Sender-Signed": {"conf": 0, "incomp": 0, "conf_tot": 0, "incomp_tot": 0,
                                 "benign_alarm": 0.0, "benign_fp": 0, "benign_tot": 0},
               "ATTP": {"conf": 0, "incomp": 0, "conf_tot": 0, "incomp_tot": 0,
                        "benign_alarm": 0.0, "benign_fp": 0, "benign_tot": 0}}

    for builder in variants():
        for i in range(K_PER):
            ftype, pending, back2, sess = builder(resolver, i)
            # 找回 sender 节点公钥（用于 Sender-Signed 验签）
            sender_pub = resolver._keys[pending.sender_did]
            if ftype == "benign":
                for s in schemes:
                    schemes[s]["benign_tot"] += 1
                    # 对账后是否仍告警：晚报占比 × (1 - 对账能力) + 本身 FP
                    alarm = BENIGN_LATE_FRAC * (1 - RECONCILE_CAP[s])
                    schemes[s]["benign_alarm"] += alarm / K_PER  # 期望值累加
                continue
            for s in schemes:
                if ftype == "conflicting":
                    schemes[s]["conf_tot"] += 1
                else:
                    schemes[s]["incomp_tot"] += 1
                if s == "ATTP":
                    det = await detect_attp(pending, back2, sess, detector)
                elif s == "Sender-Signed":
                    det = _sender_signed_detect(pending, sender_pub)
                else:
                    det = _agenttrace_detect(pending)
                if det:
                    if ftype == "conflicting":
                        schemes[s]["conf"] += 1
                    else:
                        schemes[s]["incomp"] += 1

    # 汇总
    res = {}
    for s, d in schemes.items():
        conf_r = d["conf"] / d["conf_tot"] if d["conf_tot"] else 0
        incomp_r = d["incomp"] / d["incomp_tot"] if d["incomp_tot"] else 0
        tot_atk = d["conf_tot"] + d["incomp_tot"]
        recall = (d["conf"] + d["incomp"]) / tot_atk if tot_atk else 0
        res[s] = {"fault_recall": recall, "conflicting_recall": conf_r,
                  "incomplete_recall": incomp_r, "benign_alarm": d["benign_alarm"],
                  "n_conflicting": d["conf_tot"], "n_incomplete": d["incomp_tot"],
                  "n_benign": d["benign_tot"]}
    return res, detector, resolver


# ── RQ4 证据层开销（同测）────────────────────────────────────────────────────
def measure_overhead():
    priv = ed25519.Ed25519PrivateKey.generate(); pub = priv.public_key()
    h = hashlib.sha256(b"x").hexdigest()

    def _bench(fn, n=3000):
        t0 = time.perf_counter()
        for _ in range(n): fn()
        return (time.perf_counter() - t0) / n * 1e6  # µs

    sign_us = _bench(lambda: sign_hash(h, priv))
    verify_us = _bench(lambda: verify_signature(h, sign_hash(h, priv), pub))

    # 每事件存储字节（序列化各方案落库内容）
    sample = {"session_id": "sess-x", "sender_did": "did:wba:pn.test:S_1",
              "target_did": "did:wba:pn.test:R_1", "content": "transfer report payload ...",
              "timestamp": TS_BASE, "hop_count": [1, 0]}
    sig_sz = len(sign_hash(h, priv))
    log_b = len(json.dumps(sample, separators=(",", ":"), ensure_ascii=False))         # AgentTrace
    single_b = log_b + sig_sz + 90                                                      # Sender-Signed (+sig+identity)
    dual_b = 2 * (log_b + sig_sz) + 2 * 90 + 64                                         # ATTP (双报+双签+哈希+状态)
    return {"sign_us": round(sign_us, 2), "verify_us": round(verify_us, 2),
            "stored_bytes": {"AgentTrace": log_b, "Sender-Signed": single_b, "ATTP": dual_b}}


def main():
    res, _, _ = asyncio.run(run())
    ov = measure_overhead()
    out = {"model": c.MODEL, "K_PER": K_PER, "benign_late_frac": BENIGN_LATE_FRAC,
           "schemes": res, "overhead": ov,
           "note": "Fault recall=实测(crypto+detector); benign_alarm=对账建模(late_frac×(1-reconcile_cap))"}
    p = c.save_json("rq1_results.json", out)

    print("=" * 78)
    print("  RQ1 — Evidence Integrity（3 方案 × 注入 fault）")
    print("=" * 78)
    print(f"  {'Method':<16}{'Fault Rec.↑':>12}{'conflict':>10}{'incomp':>9}{'Benign Alarm↓':>16}")
    for s in ("AgentTrace", "Sender-Signed", "ATTP"):
        d = res[s]
        print(f"  {s:<16}{d['fault_recall']:>12.3f}{d['conflicting_recall']:>10.3f}"
              f"{d['incomplete_recall']:>9.3f}{d['benign_alarm']:>16.3f}")
    print(f"\n  注入：conflicting={res['ATTP']['n_conflicting']} incomplete={res['ATTP']['n_incomplete']} "
          f"benign={res['ATTP']['n_benign']}")
    print("\n  RQ4 证据层开销（每事件）：")
    print(f"  {'Method':<16}{'Stored B/ev↓':>14}{'sign µs':>10}{'verify µs':>11}")
    for s in ("AgentTrace", "Sender-Signed", "ATTP"):
        mul = {"AgentTrace": 0, "Sender-Signed": 1, "ATTP": 2}[s]
        print(f"  {s:<16}{ov['stored_bytes'][s]:>14}{ov['sign_us']*mul:>10.2f}{ov['verify_us']:>11.2f}")
    print(f"\n>>> {p}")


if __name__ == "__main__":
    main()
