"""Horizontal Axis — 横向确认器（逐跳改版）。

横轴不再独立做全局画像，而是对纵轴筛出的 α 个可疑会话做跨会话**确认**：
确认存在连贯攻击则告警，否则判良性（消化纵轴误报）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from attp.app.logging import get_logger
from attp.core.analysis.base_models import EvidenceItem, severity_for_score
from attp.core.analysis.horizontal.models import ConfirmationVerdict
from attp.core.analysis.horizontal.prompts import CONFIRMATION_PROMPT

logger = get_logger("HorizontalAnalysis")

# field_type → sender node_type（DID 与 node_type 严格一一对应）
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
    """从 traces 中读取 did 的 node_type。"""
    for t in traces:
        if t.get("node_did") == did:
            return FIELD_TYPE_TO_SENDER_NODE_TYPE.get(t["field_type"], "agent")
    _RECEIVER_MAP: dict[str, str] = {
        "A2T": "tool", "A2U": "user", "A2A": "agent",
        "U2A": "agent", "T2A": "agent",
    }
    for t in traces:
        if t.get("target_did") == did or t.get("target") == did:
            return _RECEIVER_MAP.get(t["field_type"], "agent")
    return "agent"


def _derive_node_type_from_scores(hop_scores: list[dict], did: str) -> str:
    """从逐跳评分推导 did 的 node_type（取首条作为 sender 的 field_type）。"""
    for h in hop_scores:
        if h.get("sender_did") == did:
            return FIELD_TYPE_TO_SENDER_NODE_TYPE.get(h.get("field_type", ""), "agent")
    return "agent"


class HorizontalIntentAnalyzer:
    """跨会话确认器：对纵轴筛出的 α 个会话做综合判定。"""

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

    async def confirm(
        self,
        did: str,
        node_type: str,
        sessions_data: list[dict],
        previous_context: str = "",
        prior_report: str = "",
    ) -> ConfirmationVerdict:
        """对 α 个会话的高分跳做跨会话确认（可汇入上一次确认报告）。"""
        sessions_summary = self._format_sessions(sessions_data)
        prompt = CONFIRMATION_PROMPT.format(
            did=did,
            node_type=node_type,
            session_count=len(sessions_data),
            context=previous_context or "（首次确认，无前序上下文）",
            prior_report=prior_report or "（首次确认，无前序批次）",
            sessions_summary=sessions_summary,
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
            result = _loads_json_object(content or "", f"horizontal confirm did={did}")

            evidence_items: list[EvidenceItem] = []
            for ref in result.get("evidence_refs", []) or []:
                try:
                    tid = int(ref.get("trace_id", 0) or 0)
                except (TypeError, ValueError):
                    tid = 0
                evidence_items.append(EvidenceItem(
                    description=ref.get("reason", ""),
                    trace_ids=[tid] if tid else [],
                ))

            try:
                score = float(result.get("taint_score", 0.0))
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(10.0, score))
            severity = result.get("severity") or severity_for_score(score)

            return ConfirmationVerdict(
                did=did,
                node_type=node_type,
                confirmed=bool(result.get("confirmed", False)),
                severity=severity,
                taint_score=score,
                threat_pattern=result.get("threat_pattern", "none"),
                evidence=result.get("evidence", ""),
                evidence_items=evidence_items,
                sessions_reviewed=len(sessions_data),
                summary=result.get("summary", ""),
                context_summary=result.get("context_summary", ""),
            )
        except Exception as e:
            logger.error("Horizontal confirm failed for did={}: {}", did, e)
            return ConfirmationVerdict(
                did=did, node_type=node_type, sessions_reviewed=len(sessions_data),
            )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_sessions(sessions_data: list[dict]) -> str:
        """把各会话高分跳渲染成 prompt 文本。"""
        if not sessions_data:
            return "（无可疑会话）"
        parts = []
        for s in sessions_data:
            sid = s.get("session_id", "?")
            w = s.get("w_value", 0.0)
            hops = s.get("hops", []) or []
            lines = [f"### 会话 {sid}  (W(σ)={w:.2f}, 高分跳 {len(hops)} 条)"]
            intent = s.get("intent") or {}
            goal = intent.get("goal") or ""
            cons = intent.get("constraints") or []
            proh = intent.get("prohibitions") or []
            if goal or cons or proh:
                lines.append(
                    f"  授权意图：goal={goal or '(未抽取)'}；"
                    f"constraints={cons or '[]'}；prohibitions={proh or '[]'}"
                )
            for h in hops[:5]:
                lines.append(
                    f"  - [trace#{h.get('trace_id')}] score={h.get('score')} "
                    f"severity={h.get('severity')} type={h.get('field_type')} "
                    f"deviation={h.get('deviation_type')}"
                )
                content = (h.get("content") or "")[:200]
                if content:
                    lines.append(f"      内容: {content}")
            parts.append("\n".join(lines))
        return "\n\n".join(parts)
