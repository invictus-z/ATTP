"""Record 接收路由 — 从 DataPort 闭包重构为标准 APIRouter。"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from attp.app.logging import get_logger
from attp.core.message.event import BackMessage

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
) -> APIRouter:
    """返回 /record 路由。

    Parameters
    ----------
    orchestrator_holder : list
        长度为 1 的可变列表，用于 late-binding 注入 orchestrator。
    """
    router = APIRouter()

    @router.post("/record")
    async def receive_record(request: Request) -> JSONResponse:
        """接收并处理 record 消息。"""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        # 解析 BackMessage
        try:
            back_msg = BackMessage.from_dict(body)
        except Exception as e:
            return JSONResponse({"error": f"Invalid BackMessage: {e}"}, status_code=400)

        session_id = back_msg.recorded_hop.session_id
        pna = back_msg.protocol_url

        # === Nonce 验证管道 ===
        from attp.protocol_node.engine.middleware import intercept_record

        result = await intercept_record(
            back_msg, did_resolver, tracer,
            session_manager=session_manager,
            malicious_detector=malicious_detector,
        )

        if result.status == "error":
            error_key = result.error.split(":")[0] if result.error else ""
            code, msg = ERROR_MAP.get(
                error_key, (500, result.error or "Unknown error")
            )
            logger.error(
                "Record rejected: session={}, error_key={}, detail={}",
                session_id, error_key, result.error,
            )
            return JSONResponse({"error": msg}, status_code=code)

        if result.status == "stored":
            logger.info("Record stored (pending): session={}", session_id)
            return JSONResponse({"status": "stored"})

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

            await tracer.save_behavior_entry(
                session_id=session_id,
                protocol_node_address=pna,
                node_did=stored.sender_did,
                hop_count=stored.hop.get("Hop_Count", [0, 0]),
                field_type=behavior_type,
                content=stored.hop.get("Content", ""),
                target=stored.hop.get("target_did", ""),
                timestamp=stored.hop.get("Timestamp", 0),
            )
            logger.info(
                "BehaviorEntry saved: sender={}, receiver={}, type={}",
                stored.sender_did, result.sender_did, behavior_type,
            )

            await behavior_controller.handle(
                behavior_type, body, result,
            )

            _orch = orchestrator_holder[0]
            if behavior_type == "U2A" and _orch and session_id:
                content = stored.hop.get("Content", "")
                await _orch.on_field_U2A_recorded(session_id, content)

            if _orch and session_id:
                await _orch.on_record_received(session_id)

            return JSONResponse({"status": "Record verified and saved"})

    return router