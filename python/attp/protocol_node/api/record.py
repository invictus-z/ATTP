"""Record 接收路由 — 从 DataPort 闭包重构为标准 APIRouter。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from attp.app.logging import get_logger
from attp.core.message.event import BackMessage
from attp.core.sse import EventType, Topic

if TYPE_CHECKING:
    from attp.core.sse import EventBroker

logger = get_logger("RecordAPI")

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


def get_record_router(
    tracer,
    session_manager,
    did_resolver,
    behavior_controller,
    malicious_detector,
    orchestrator_holder: list,
    event_broker: EventBroker | None = None,
) -> APIRouter:
    """返回 /record 路由。

    Parameters
    ----------
    orchestrator_holder : list
        长度为 1 的可变列表，用于 late-binding 注入 orchestrator。
    event_broker : EventBroker | None
        事件总线；非 None 时在回传处理 error 出口发布 ``record.error`` 事件。
    """
    router = APIRouter()

    async def _publish_record_error(
        *, back_msg: BackMessage | None = None, body: dict | None = None,
        error_key: str, error_message: str, status_code: int,
    ) -> None:
        """发布 record.error 事件（None-safe）。优先用已解析的 back_msg，否则 best-effort 从 raw body 取。"""
        if not event_broker:
            return
        session_id = nonce = node_did = protocol_url = sender_did = target_did = ""
        hop_count: list = []
        if back_msg is not None:
            recorded = back_msg.recorded_hop
            session_id = recorded.session_id
            nonce = back_msg.nonce
            node_did = back_msg.node_did
            protocol_url = back_msg.protocol_url
            hop_count = list(recorded.hop_count)
            sender_did = recorded.sender_did
            target_did = recorded.target_did
        elif isinstance(body, dict):
            rh = body.get("recorded_hop") or {}
            session_id = rh.get("session_id", "")
            nonce = body.get("nonce", "")
            node_did = body.get("node_did", "")
            protocol_url = body.get("protocol_url", "")
            hop_count = rh.get("hop_count", [])
            sender_did = rh.get("sender_did", "")
            target_did = rh.get("target_did", "")
        await event_broker.publish(
            EventType.RECORD_ERROR,
            {
                "session_id": session_id,
                "nonce": nonce,
                "node_did": node_did,
                "protocol_url": protocol_url,
                "hop_count": hop_count,
                "sender_did": sender_did,
                "target_did": target_did,
                "error_key": error_key,
                "error_message": error_message,
                "status_code": status_code,
            },
            topic=Topic.RECORD,
        )

    @router.post("/record")
    async def receive_record(request: Request) -> JSONResponse:
        """接收并处理 record 消息。"""
        try:
            body = await request.json()
        except Exception:
            await _publish_record_error(
                error_key="invalid_json", error_message="Invalid JSON body", status_code=400,
            )
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # 解析 BackMessage
        try:
            back_msg = BackMessage.from_dict(body)
        except Exception as e:
            await _publish_record_error(
                body=body, error_key="invalid_backmessage",
                error_message=f"Invalid BackMessage: {e}", status_code=400,
            )
            return JSONResponse({"error": f"Invalid BackMessage: {e}"}, status_code=400)

        session_id = back_msg.recorded_hop.session_id
        pna = back_msg.protocol_url

        # === Nonce 验证管道 ===
        from attp.protocol_node.engine.middleware import intercept_record

        try:
            result = await intercept_record(
                back_msg, did_resolver, tracer,
                session_manager=session_manager,
                malicious_detector=malicious_detector,
            )
        except Exception as e:
            logger.error("intercept_record unhandled exception: session={}, error={}", session_id, e)
            await _publish_record_error(
                back_msg=back_msg, error_key="internal_error",
                error_message=f"Internal error: {e}", status_code=500,
            )
            return JSONResponse({"error": f"Internal error: {e}"}, status_code=500)

        if result.status == "error":
            error_key = result.error.split(":")[0] if result.error else ""
            code, msg = ERROR_MAP.get(
                error_key, (500, result.error or "Unknown error")
            )
            logger.error(
                "Record rejected: session={}, error_key={}, detail={}",
                session_id, error_key, result.error,
            )
            await _publish_record_error(
                back_msg=back_msg, error_key=error_key, error_message=msg, status_code=code,
            )
            return JSONResponse({"error": msg}, status_code=code)

        if result.status == "stored":
            logger.info("Record stored (pending): session={}", session_id)
            return JSONResponse({
                "status": "stored",
                "nonce": back_msg.nonce,
                "session_id": session_id,
            })

        if result.status == "malicious":
            report = result.malicious_report
            logger.warning(
                "Malicious node detected: session={}, dids={}, type={}",
                session_id,
                report.malicious_dids if report else [],
                report.evidence_type.value if report else "unknown",
            )
            return JSONResponse(
                {
                    "status": "malicious_detected",
                    "malicious_dids": report.malicious_dids if report else [],
                    "evidence_type": report.evidence_type.value if report else "",
                    "description": report.evidence_description if report else "",
                },
                status_code=403,
            )

        if result.status == "verified":
            behavior_type = result.behavior_type
            stored = result.stored_msg

            trace_id = await tracer.save_behavior_entry(
                session_id=session_id,
                protocol_node_address=pna,
                sender_did=stored.node_did, #验证过的真实的发送方DID
                target_did=result.sender_did, #验证过的真实的接收方DID
                hop_count=stored.hop.get("Hop_Count", [0, 0]),
                field_type=behavior_type,
                content=stored.hop.get("Content", ""),
                timestamp=stored.hop.get("Timestamp", 0),
            )
            logger.info(
                "BehaviorEntry saved: sender={}, receiver={}, type={}",
                stored.node_did, result.sender_did, behavior_type,
            )

            await behavior_controller.handle(
                result.node_type, body, result,
            )

            # 逐跳异步：落库后把该跳投进会话的有界队列（不等 LLM）；
            # worker 内部按 field_type 分流（U2A 抽意图 / 动作跳打分）。
            _orch = orchestrator_holder[0]
            if _orch and session_id:
                hop = {
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "sender_did": stored.node_did,      # 验证过的发送方
                    "field_type": behavior_type,
                    "hop_count": stored.hop.get("Hop_Count", [0, 0]),
                    "content": stored.hop.get("Content", ""),
                    "target": result.sender_did,         # 验证过的接收方
                    "timestamp": stored.hop.get("Timestamp", 0),
                }
                await _orch.enqueue_trace(session_id, hop)

            return JSONResponse({"status": "Record verified and saved"})

    return router
