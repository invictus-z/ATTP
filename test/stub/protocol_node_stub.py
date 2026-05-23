"""Protocol Node Record API 存根 — 用于测试。

模拟真实 Protocol Node 的 POST /record 端点，接受与真实 API 相同格式的 BackMessage JSON，
返回模拟响应。

用法::

    # 1. 编程方式
    from test.stub.protocol_node_stub import create_stub_app, StubConfig

    cfg = StubConfig(force_status="stored")
    app = create_stub_app(cfg)

    # 配合 httpx.AsyncClient 测试
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.post("/record", json=back_msg_dict)

    # 2. 命令行启动
    python -m test.stub.protocol_node_stub
    # 默认监听 0.0.0.0:9999，可通过环境变量 STUB_HOST / STUB_PORT 自定义
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ---------------------------------------------------------------------------
# StubConfig — 存根行为配置
# ---------------------------------------------------------------------------

@dataclass
class StubConfig:
    """控制存根的响应行为。

    Attributes:
        force_status: 强制返回的状态。
            - "stored":    回传1 到达，暂存（默认）
            - "verified":  回传2 验证通过
            - "malicious": 恶意节点检测
            - "error":     验证失败
            - "auto":      根据请求中同一个 nonce 自动切换
                           （第 1 次同一 nonce 返回 stored，第 2 次返回 verified）
            - None / "auto": 同 "auto"
        latency:  模拟处理延迟（秒），默认 0
        record_history: 是否在内存中保存所有收到的 record，默认 True
    """

    force_status: str | None = "auto"
    latency: float = 0.0
    record_history: bool = True


@dataclass
class StubState:
    """存根运行时状态。"""

    records: list[dict[str, Any]] = field(default_factory=list)
    nonce_counts: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 错误映射（与真实 record.py 保持一致）
# ---------------------------------------------------------------------------

ERROR_MAP: dict[str, tuple[int, str]] = {
    "missing_record_log": (400, "Missing Record_Log"),
    "hop_validation": (400, "Hop validation failed"),
    "did_resolution_failed": (404, "DID resolution failed"),
    "missing_type_field": (400, "Missing ATTPNodeType"),
    "invalid_type": (400, "Invalid ATTP node type"),
    "missing_nonce": (400, "Missing nonce"),
    "missing_identity_signature": (400, "Missing Identity_Signature"),
    "identity_signature_invalid": (403, "Identity signature invalid"),
    "sender_mismatch_not_self": (403, "Sender mismatch"),
    "receiver_mismatch": (403, "Receiver mismatch"),
    "back_propagation": (403, "Back-propagation verification failed"),
    "invalid_type_combination": (400, "Invalid type combination"),
    "hop_count_violation_a2a": (400, "Hop count violation (A2A: [0] must +1, [1] must be 0)"),
    "hop_count_violation_non_a2a": (400, "Hop count violation (non-A2A: [0] must stay, [1] must +1)"),
    "hop_zero_must_be_u2a": (400, "hop_count=[0,0] must be U2A (user intent)"),
    "content_signature_invalid": (403, "Content signature invalid"),
    "trusted_list_violation": (403, "Trusted list violation"),
}


# ---------------------------------------------------------------------------
# 工厂函数
# ---------------------------------------------------------------------------

def create_stub_app(config: StubConfig | None = None) -> FastAPI:
    """创建模拟 /record API 的 FastAPI 应用。

    Parameters
    ----------
    config : StubConfig, optional
        存根行为配置，默认使用 ``StubConfig()``。

    Returns
    -------
    FastAPI
        可直接用于 httpx.AsyncClient 或 uvicorn 的 FastAPI 实例。
    """
    if config is None:
        config = StubConfig()

    state = StubState()
    app = FastAPI(title="ATTP Protocol Node (Stub)")

    @app.get("/api/status")
    async def get_status():
        """健康检查。"""
        return {"status": "ok", "service": "protocol_node_stub"}

    @app.post("/record")
    async def receive_record(request: Request) -> JSONResponse:
        """接收并处理 record 消息 — 存根版本。"""
        # 模拟延迟
        if config.latency > 0:
            import asyncio
            await asyncio.sleep(config.latency)

        # 解析 JSON
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # 基本结构校验：检查 recorded_hop 是否存在
        recorded_hop = body.get("recorded_hop")
        if not recorded_hop:
            return JSONResponse({"error": "Missing Record_Log"}, status_code=400)

        session_id = recorded_hop.get("session_id", "unknown")
        nonce = body.get("nonce", "")

        # 记录历史
        if config.record_history:
            state.records.append({
                "timestamp": time.time(),
                "session_id": session_id,
                "nonce": nonce,
                "body": body,
            })

        # ---- 根据 force_status 决定响应 ----
        status = config.force_status
        if status is None or status == "auto":
            status = "auto"

        if status == "auto":
            # 自动模式：同一 nonce 第 1 次返回 stored，第 2 次返回 verified
            count = state.nonce_counts.get(nonce, 0) + 1
            state.nonce_counts[nonce] = count
            if count == 1:
                resolved_status = "stored"
            else:
                resolved_status = "verified"
        else:
            resolved_status = status

        if resolved_status == "stored":
            return JSONResponse({"status": "stored"})

        if resolved_status == "verified":
            return JSONResponse({"status": "Record verified and saved"})

        if resolved_status == "malicious":
            return JSONResponse(
                {
                    "status": "malicious_detected",
                    "malicious_dids": [body.get("node_did", "did:wba:stub:malicious")],
                    "evidence_type": "identity_mismatch",
                    "description": "Stub: simulated malicious detection",
                },
                status_code=403,
            )

        if resolved_status == "error":
            error_key = "hop_validation"
            code, msg = ERROR_MAP.get(error_key, (500, "Unknown error"))
            return JSONResponse({"error": msg}, status_code=code)

        # fallback
        return JSONResponse({"status": "stored"})

    @app.get("/stub/history")
    async def get_history():
        """查看存根收到的所有 record（调试用）。"""
        return {
            "total": len(state.records),
            "records": state.records,
        }

    @app.delete("/stub/history")
    async def clear_history():
        """清空历史记录。"""
        state.records.clear()
        state.nonce_counts.clear()
        return {"cleared": True}

    # 将 config 和 state 挂到 app 上方便外部访问
    app.state.stub_config = config
    app.state.stub_state = state

    return app


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main():
    """命令行启动存根服务。"""
    import uvicorn

    host = os.environ.get("STUB_HOST", "0.0.0.0")
    port = int(os.environ.get("STUB_PORT", "9999"))
    force = os.environ.get("STUB_FORCE_STATUS", "auto")

    config = StubConfig(force_status=force)
    app = create_stub_app(config)

    print(f"[stub] Protocol Node Record Stub starting at {host}:{port}")
    print(f"[stub] force_status={force}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()