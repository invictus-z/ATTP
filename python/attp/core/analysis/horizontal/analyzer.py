"""Horizontal Axis — 横向语义意图追踪器。

按 node_type 选择隔离的 Prompt 模板，对单个 DID 跨所有 Session 的行为进行全局分析。
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from attp.app.logging import get_logger
from attp.core.analysis.base_models import EvidenceItem
from attp.core.analysis.horizontal.models import (
    CrossSessionProfile,
    DIDVerdict,
    HorizontalIntentReport,
)
from attp.core.analysis.horizontal.prompts import HORIZONTAL_PROMPT_MAP

logger = get_logger("HorizontalAnalysis")

# field_type → sender node_type (DID与node_type严格一一对应)
FIELD_TYPE_TO_SENDER_NODE_TYPE: dict[str, str] = {
    "A2T": "agent", "A2U": "agent", "A2A": "agent",
    "U2A": "user",
    "T2A": "tool",
}


def _loads_json_object(raw_content: str, context: str) -> dict[str, Any]:
    text = (raw_content or "").strip()
    if not text:
        raise ValueError(f"empty LLM response for {context}")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()

    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

    return json.loads(text)


def _derive_node_type(traces: list[dict], did: str) -> str:
    """从 traces 中直接读取 did 的 node_type。

    一个DID只对应一种node_type，取第一条作为sender的trace的field_type即可。
    """
    for t in traces:
        if t.get("node_did") == did:
            return FIELD_TYPE_TO_SENDER_NODE_TYPE.get(t["field_type"], "agent")
    # fallback: 该DID仅作为target出现，从接收视角推导
    _RECEIVER_MAP: dict[str, str] = {
        "A2T": "tool", "A2U": "user", "A2A": "agent",
        "U2A": "agent", "T2A": "agent",
    }
    for t in traces:
        if t.get("target_did") == did or t.get("target") == did:
            return _RECEIVER_MAP.get(t["field_type"], "agent")
    return "agent"


class HorizontalIntentAnalyzer:
    """Analyzes cross-session behavior for a single DID using LLM."""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        client: AsyncOpenAI | None = None,
    ):
        if client is not None:
            self._client = client
        else:
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def analyze(
        self,
        did: str,
        node_type: str,
        batch_index: int,
        from_trace_id: int,
        to_trace_id: int,
        traces: list[dict],
        previous_context: str = "",
    ) -> HorizontalIntentReport:
        """Run horizontal analysis for a DID across sessions."""
        profile = self._build_cross_session_profile(traces, did, node_type)
        sessions_scanned = len(profile.sessions_involved)

        prompt_template = HORIZONTAL_PROMPT_MAP.get(node_type, HORIZONTAL_PROMPT_MAP["agent"])
        profile_str = self._format_profile(profile)
        prompt = prompt_template.format(
            did=did,
            session_count=sessions_scanned,
            context=previous_context or "（首次横向分析，无前序上下文）",
            cross_session_profile=profile_str,
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "你是一个多Agent系统的跨Session安全审计专家，只输出 JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=120,
            )
            content = response.choices[0].message.content
            result = _loads_json_object(content or "", f"horizontal analysis for did={did}")

            evidence_items = []
            for ref in result.get("evidence_refs", []):
                evidence_items.append(EvidenceItem(
                    description=ref.get("reason", result.get("evidence", "")),
                    trace_ids=[ref.get("trace_id", 0)],
                ))

            verdict = DIDVerdict(
                did=did,
                node_type=node_type,
                sessions_analyzed=sessions_scanned,
                aligned=result.get("aligned", True),
                deviation_type=result.get("deviation_type", "none"),
                threat_pattern=result.get("threat_pattern", "none"),
                evidence=result.get("evidence", ""),
                evidence_items=evidence_items,
                severity=result.get("severity", "none"),
                taint_score=result.get("taint_score", 0.0),
            )

            overall = "clean"
            if verdict.taint_score >= 0.7:
                overall = "malicious"
            elif verdict.taint_score >= 0.3:
                overall = "suspicious"

            return HorizontalIntentReport(
                did=did,
                node_type=node_type,
                batch_index=batch_index,
                from_trace_id=from_trace_id,
                to_trace_id=to_trace_id,
                sessions_scanned=sessions_scanned,
                did_verdict=verdict,
                overall_verdict=overall,
                summary=result.get("summary", ""),
                context_summary=result.get("context_summary", ""),
            )
        except Exception as e:
            logger.error("Horizontal analysis failed for did={}: {}", did, e)
            return HorizontalIntentReport(
                did=did,
                node_type=node_type,
                batch_index=batch_index,
                from_trace_id=from_trace_id,
                to_trace_id=to_trace_id,
                sessions_scanned=sessions_scanned,
                did_verdict=DIDVerdict(did=did, node_type=node_type, sessions_analyzed=sessions_scanned),
                overall_verdict="error",
                summary=f"Horizontal analysis failed: {e}",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cross_session_profile(
        self, traces: list[dict], did: str, node_type: str,
    ) -> CrossSessionProfile:
        """Build a CrossSessionProfile from traces for the given DID."""
        sessions: set[str] = set()
        field_a: list[dict] = []
        field_b: list[dict] = []
        field_c: list[dict] = []
        field_d: list[dict] = []
        field_e: list[dict] = []
        received: list[dict] = []
        timestamps: list[float] = []

        for t in traces:
            sid = t.get("session_id", "")
            ft = t.get("field_type", "")
            ts = t.get("timestamp")
            if ts:
                timestamps.append(ts)

            entry = {
                "id": t.get("id", 0),
                "session_id": sid,
                "content": t.get("content", ""),
                "target": t.get("target", ""),
                "timestamp": ts,
                "field_type": ft,
            }

            sender_did = t.get("node_did", "")
            target_did = t.get("target_did", t.get("target", ""))

            if sender_did == did:
                # DID is sender
                sessions.add(sid)
                if ft == "A2T":
                    field_a.append(entry)
                elif ft == "A2U":
                    field_b.append(entry)
                elif ft == "U2A":
                    field_c.append(entry)
                elif ft == "A2A":
                    field_d.append(entry)
                elif ft == "T2A":
                    field_e.append(entry)
            elif target_did == did:
                # DID is receiver
                sessions.add(sid)
                received.append(entry)

        time_span = (min(timestamps), max(timestamps)) if timestamps else None

        return CrossSessionProfile(
            did=did,
            node_type=node_type,
            sessions_involved=sorted(sessions),
            field_a_traces=field_a,
            field_b_traces=field_b,
            field_c_traces=field_c,
            field_d_traces=field_d,
            field_e_traces=field_e,
            received_traces=received,
            time_span=time_span,
        )

    def _format_profile(self, profile: CrossSessionProfile) -> str:
        """Format CrossSessionProfile for the LLM prompt."""
        lines = [
            f"DID: {profile.did}",
            f"Node Type: {profile.node_type}",
            f"Sessions: {len(profile.sessions_involved)} 个 ({', '.join(profile.sessions_involved[:10])})",
        ]
        if profile.time_span:
            lines.append(f"Time Span: {profile.time_span[0]:.0f} ~ {profile.time_span[1]:.0f}")

        if profile.field_a_traces:
            lines.append("\n**A2T (Agent→Tool) 调用:**")
            for t in profile.field_a_traces:
                lines.append(f'  - [session={t["session_id"][:16]}, trace#{t["id"]}] 目标: {t["target"]}, 内容: {t["content"][:200]}')

        if profile.field_b_traces:
            lines.append("\n**A2U (Agent→User) 回复:**")
            for t in profile.field_b_traces:
                lines.append(f'  - [session={t["session_id"][:16]}, trace#{t["id"]}] 内容: {t["content"][:200]}')

        if profile.field_c_traces:
            lines.append("\n**U2A (User→Agent) 输入:**")
            for t in profile.field_c_traces:
                lines.append(f'  - [session={t["session_id"][:16]}, trace#{t["id"]}] 内容: {t["content"][:200]}')

        if profile.field_d_traces:
            lines.append("\n**A2A (Agent→Agent) 消息:**")
            for t in profile.field_d_traces:
                lines.append(f'  - [session={t["session_id"][:16]}, trace#{t["id"]}] 目标: {t["target"]}, 内容: {t["content"][:200]}')

        if profile.field_e_traces:
            lines.append("\n**T2A (Tool→Agent) 返回:**")
            for t in profile.field_e_traces:
                lines.append(f'  - [session={t["session_id"][:16]}, trace#{t["id"]}] 内容: {t["content"][:200]}')

        if profile.received_traces:
            lines.append(f"\n**接收到的消息 ({len(profile.received_traces)} 条):**")
            for t in profile.received_traces[:20]:
                lines.append(f'  - [session={t["session_id"][:16]}, trace#{t["id"]}] type={t["field_type"]}, 内容: {t["content"][:150]}')

        return "\n".join(lines)
