"""RQ4 — 实测回传网络传输时间（完整跑一遍 ATTP /record）。

起真 ProtocolPort(uvicorn) + 内存 DID 解析器（注册本地 key，不联网），httpx 打 POST /record
（合法签名 BackMessage，Branch A 存 pending），测 HTTP 往返。
  /api/status RTT = 回环网络 + 协议栈（≈网络传输 floor）
  /record    RTT = 回环网络 + ATTP 处理(DID 解析/校验/落库)
  => 网络传输 ≈ status RTT；ATTP 处理增量 ≈ record − status
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519
from loguru import logger as _l
_l.remove()

from attp.core.pn_tracer import ProtocolTracer
from attp.core.sessions.protocol_node import ProtocolSessionManager
from attp.core.authentication.did_resolver import DIDResolutionResult
from attp.protocol_node.engine.behavior_controller import BehaviorController
from attp.protocol_node.engine.malicious_detector import MaliciousNodeDetector
from attp.protocol_node.ports.protocol_port import ProtocolPort
from attp.core.authentication.signatures import sign_hash
from attp.core.message.event import BackMessage, RecordedHop

import sys as _sys
from pathlib import Path as _Path
_BENCH_ROOT = _Path(__file__).resolve().parents[2]       # test/benchmark
if str(_BENCH_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT))                # intent_analysis 包
if str(_BENCH_ROOT.parent.parent / "python") not in _sys.path:
    _sys.path.insert(0, str(_BENCH_ROOT.parent.parent / "python"))  # attp.core.*
from intent_analysis.rq import rq_common as c  # noqa: E402

HOST, PORT = "127.0.0.1", 9912
N = 60


class LocalResolver:
    """内存 DID 解析器：注册本地 key + node_type，避免联网解析。"""
    def __init__(self):
        self._keys: dict[str, tuple] = {}

    def register(self, did, pub, ntype="agent"):
        self._keys[did] = (pub, ntype)

    async def resolve_full(self, did, key_fragment="key-1"):
        k = self._keys.get(did)
        if k:
            return DIDResolutionResult(public_key=k[0], node_type=k[1], from_cache=True)
        return DIDResolutionResult(public_key=None)


async def _pct(lats, p):
    lats = sorted(lats)
    return lats[min(len(lats) - 1, int(len(lats) * p))]


async def main():
    db = str(c.RQ_RES / "rq4_rtt_node.db")
    for f in (db, db + "-wal", db + "-shm"):
        if Path(f).exists():
            Path(f).unlink()
    # WAL 降噪存储写
    import sqlite3
    cc = sqlite3.connect(db); cc.execute("PRAGMA journal_mode=WAL"); cc.commit(); cc.close()

    tracer = await ProtocolTracer.create(db)
    smgr = ProtocolSessionManager(storage=tracer.storage)
    resolver = LocalResolver()
    priv = ed25519.Ed25519PrivateKey.generate(); pub = priv.public_key()
    did = "did:wba:pn.test:agent_1"
    resolver.register(did, pub, "agent")
    port = ProtocolPort(
        tracer=tracer, session_manager=smgr, host=HOST, port=PORT,
        did_resolver=resolver, behavior_controller=BehaviorController(),
        malicious_detector=MaliciousNodeDetector(resolver))
    await port.start()

    # 等 uvicorn 起来
    base = f"http://{HOST}:{PORT}"
    async with httpx.AsyncClient(base_url=base) as cli:
        up = False
        for _ in range(40):
            try:
                r = await cli.get("/api/status", timeout=1.0)
                if r.status_code < 500:
                    up = True; break
            except Exception:
                await asyncio.sleep(0.25)
        if not up:
            print("[!] 服务未就绪"); await port.stop(); return

        # 构造合法签名 BackMessage（Branch A：reporter 自报）
        def make_body(i):
            rh = RecordedHop(f"rtt-s{i}", did, "did:wba:pn.test:agent_2",
                             f"payload-{i}", time.time(), [1, 0])
            rh.sig_content = sign_hash(rh.content_hash(), priv)
            bm = BackMessage(protocol_url=base, node_did=did, nonce=f"n{i}",
                             sig_identity="", recorded_hop=rh)
            bm.sign_identity(priv)
            return bm.to_dict()

        # warmup
        for i in range(5):
            await cli.post("/record", json=make_body(1000 + i))

        # 测 /record（回环 + ATTP 处理）
        rec = []
        for i in range(N):
            b = make_body(i)
            t0 = time.perf_counter()
            r = await cli.post("/record", json=b)
            rec.append((time.perf_counter() - t0) * 1000)
        # 测 /api/status（回环网络 + 协议栈 floor）
        st = []
        for _ in range(N):
            t0 = time.perf_counter()
            await cli.get("/api/status")
            st.append((time.perf_counter() - t0) * 1000)

    await port.stop()

    rec_p50, rec_p95 = await _pct(rec, 0.5), await _pct(rec, 0.95)
    st_p50, st_p95 = await _pct(st, 0.5), await _pct(st, 0.95)
    out = {
        "record_p50_ms": round(rec_p50, 3), "record_p95_ms": round(rec_p95, 3),
        "status_p50_ms": round(st_p50, 3), "status_p95_ms": round(st_p95, 3),
        "network_floor_p50_ms": round(st_p50, 3),
        "attp_processing_delta_p50_ms": round(rec_p50 - st_p50, 3),
        "n": N,
        "note": "loopback(127.0.0.1) HTTP 往返；部署跨机 RTT 更高(LAN 0.5-2ms / WAN 10-50ms)",
    }
    p = c.save_json("rq4_rtt_live.json", out)
    print(f"  /record     RTT  P50={rec_p50:.3f}ms  P95={rec_p95:.3f}ms  (回环网络 + ATTP 处理)")
    print(f"  /api/status RTT  P50={st_p50:.3f}ms  P95={st_p95:.3f}ms  (回环网络 floor)")
    print(f"  => 一次网络传输(loopback) ≈ {st_p50:.3f}ms ; ATTP 处理增量 ≈ {rec_p50-st_p50:.3f}ms")
    print(f"  (部署跨机 RTT 更高：LAN 0.5-2ms / WAN 10-50ms)")
    print(f"  -> {p}")


if __name__ == "__main__":
    asyncio.run(main())
