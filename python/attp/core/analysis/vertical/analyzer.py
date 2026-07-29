"""Vertical Axis — 纵向逐跳 V-Reasoner。

- ``extract_intent_revision``：每条发起者 U2A 抽一个意图增量 Δ。
- ``score_hop``：逐跳评分（输入三元组 I/h_{i-1}/a_i，输出 4 维 + h_i）；
  s_i / breadth / severity / overall 均由代码推导（不让 LLM 下）。
- ``aggregate_session``：把会话内逐跳评分聚合成 ``VerticalSessionReport``。
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from attp.app.logging import get_logger
from attp.core.analysis.base_models import (
    SCORE_MAX,
    EvidenceItem,
    HopScore,
    IntentRevision,
    IntentRevisionSource,
    aggregate_score,
    compute_breadth,
    overall_verdict_for_severities,
    severity_for_score,
)
from attp.core.analysis.vertical.models import VerticalSessionReport
from attp.core.analysis.vertical.prompts import HOP_SCORING_PROMPT, INTENT_REVISION_PROMPT

logger = get_logger("VerticalAnalysis")

# field_type → sender node_type（与 HorizontalIntentAnalyzer 一致）
FIELD_TYPE_TO_SENDER_NODE_TYPE: dict[str, str] = {
    "A2T": "agent", "A2U": "agent", "A2A": "agent",
    "U2A": "user",
    "T2A": "tool",
}

_FIELD_TYPE_DESC: dict[str, str] = {
    "A2A": "Agent→Agent 消息",
    "A2T": "Agent→Tool 工具调用",
    "A2U": "Agent→User 回复",
    "T2A": "Tool→Agent 返回",
    "U2A": "User→Agent 输入（发起者用于设定意图不打分；非发起者作为可疑行为打分）",
}

# LLM 返回的维度 key → 内部顺序（DIMENSION_NAMES）
_DIM_KEYS: tuple[str, ...] = (
    "d1_intent_alignment",
    "d2_capability",
    "d3_injection_manipulation",
    "d4_exfiltration_tampering",
)


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


def _round_step(x: float, step: float = 0.5) -> float:
    """按 step 量化（默认 0.5）。"""
    if step <= 0:
        return x
    return round(x / step) * step


def _build_dimensions(
    dims_raw: dict[str, Any] | None,
    aggregation: str | float = "max",
) -> tuple[list[float], float, int]:
    """解析 LLM 原始维度 → (固定 4 维数组[缺失=0], 聚合分, breadth)。

    缺失维度（LLM 未给出的 key）**不补 0 参与聚合**——补 0 会让 mean 聚合被稀释
    （漏报：在场的几个高分维被未评估维的 0 拉低，例如 d1=9/d2=8、d3,d4 缺失时
    mean(9,8,0,0)=4.25 而非在场均值 8.5）。聚合只在 LLM 实际给出的维度上算：

      - ``max``：在场最大（缺失维本就不影响）；
      - ``sum``(mean)：在场均值（等价把在场权重放大到 N/k，不被缺失稀释）；
      - 数值 p(L^p)：在场维度的范数。

    固定 4 维数组里缺失位记 0，仅供落库 dim1..dim4 与 breadth 统计；全部缺失则 score=0。
    """
    full: list[float] = []
    present: list[float] = []
    for key in _DIM_KEYS:
        provided = bool(dims_raw) and key in dims_raw
        try:
            val = float(dims_raw.get(key, 0.0)) if provided else 0.0
        except (TypeError, ValueError):
            val = 0.0
        val = max(0.0, min(SCORE_MAX, _round_step(val)))
        full.append(val)
        if provided:
            present.append(val)
    score = _round_step(aggregate_score(present, aggregation)) if present else 0.0
    score = max(0.0, min(SCORE_MAX, score))
    return full, score, compute_breadth(full)


def _derive_node_type(traces: list[dict], did: str) -> str:
    """从 traces 中推导指定 DID 的 node_type（与横轴一致）。"""
    for t in traces:
        if t.get("node_did") == did:
            return FIELD_TYPE_TO_SENDER_NODE_TYPE.get(t["field_type"], "agent")
    _RECEIVER_MAP: dict[str, str] = {
        "A2T": "tool", "A2U": "user", "A2A": "agent",
        "U2A": "agent", "T2A": "agent",
    }
    for t in traces:
        target = t.get("target_did") or t.get("target", "")
        if target == did:
            return _RECEIVER_MAP.get(t["field_type"], "agent")
    return "agent"


class VerticalIntentAnalyzer:
    """逐跳 V-Reasoner：意图增量抽取 + 单跳 4 维评分。"""

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        client: AsyncOpenAI | None = None,
        aggregation: str | float = "max",
    ):
        if client is not None:
            self._client = client
        else:
            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._aggregation = aggregation

    # ------------------------------------------------------------------
    # 意图增量抽取
    # ------------------------------------------------------------------

    async def extract_intent_revision(
        self,
        u2a_content: str,
        previous_revisions: list[dict] | None = None,
        source: IntentRevisionSource | None = None,
    ) -> IntentRevision:
        """从一条 U2A 抽意图增量 Δ。失败时用 U2A 原文兜底构造（不阻塞）。"""
        prev_str = self._format_revisions(previous_revisions or [])
        prompt = INTENT_REVISION_PROMPT.format(
            u2a_content=(u2a_content or "")[:1000],
            previous_revisions=prev_str,
        )
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "你是一个安全审计助手，只输出 JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=120,
            )
            content = response.choices[0].message.content
            data = _loads_json_object(content or "", "intent revision")
            return IntentRevision(
                goal=data.get("goal", ""),
                constraints=data.get("constraints", []),
                prohibitions=data.get("prohibitions", []),
                source=source,
            )
        except Exception as e:
            logger.warning("Intent revision extraction failed, using U2A raw fallback: {}", e)
            # 兜底：用 U2A 原文构造最小 Δ
            return IntentRevision(
                goal=(u2a_content or "")[:200],
                constraints=[],
                prohibitions=[],
                source=source,
            )

    # ------------------------------------------------------------------
    # 逐跳评分
    # ------------------------------------------------------------------

    async def score_hop(
        self,
        hop: dict,
        intent_revisions: list[dict],
        hidden_state_prev: str,
    ) -> HopScore | None:
        """对单条动作跳评分。失败返回 None（调用方决定是否推进游标）。"""
        trace_id = hop.get("trace_id", 0)
        field_type = hop.get("field_type", "")
        prompt = HOP_SCORING_PROMPT.format(
            intent=self._format_revisions(intent_revisions),
            hidden_state_prev=hidden_state_prev or "（会话起始，无前序隐状态）",
            field_type=field_type,
            field_type_desc=_FIELD_TYPE_DESC.get(field_type, field_type),
            sender_did=hop.get("sender_did", ""),
            target=hop.get("target", ""),
            hop_content=(hop.get("content", "") or "")[:1000],
            trace_id_placeholder=trace_id,
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "你是一个多Agent系统安全审计员，只输出 JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                timeout=120,
            )
            content = response.choices[0].message.content
            result = _loads_json_object(content or "", f"hop scoring trace={trace_id}")
            return self._build_hop_score(hop, result)
        except Exception as e:
            logger.error("Hop scoring failed for trace={}: {}", trace_id, e)
            return None

    def _build_hop_score(self, hop: dict, result: dict[str, Any]) -> HopScore:
        """把 LLM 结果 + 代码推导组装成 HopScore。"""
        dims, score, breadth = _build_dimensions(
            result.get("dimensions"), self._aggregation,
        )
        severity = severity_for_score(score)

        evidence_items: list[EvidenceItem] = []
        for ref in result.get("evidence_refs", []) or []:
            try:
                tid = int(ref.get("trace_id", hop.get("trace_id", 0)) or 0)
            except (TypeError, ValueError):
                tid = hop.get("trace_id", 0)
            evidence_items.append(EvidenceItem(
                description=ref.get("reason", ""),
                trace_ids=[tid],
                field_type=hop.get("field_type", ""),
            ))

        return HopScore(
            trace_id=hop.get("trace_id", 0),
            session_id=hop.get("session_id", ""),
            sender_did=hop.get("sender_did", ""),
            field_type=hop.get("field_type", ""),
            hop_count=list(hop.get("hop_count", [0, 0])),
            score=score,
            dimensions=dims,
            breadth=breadth,
            severity=severity,
            deviation_type=result.get("deviation_type", "none"),
            evidence_items=evidence_items,
            hidden_state=result.get("hidden_state", ""),
            timestamp=hop.get("timestamp", 0.0),
        )

    # ------------------------------------------------------------------
    # 会话聚合（只读端点用）
    # ------------------------------------------------------------------

    @staticmethod
    def aggregate_session(
        session_id: str,
        hop_scores: list[dict],
        intent_revisions: list[dict],
        hidden_state: str,
        initiator_did: str = "",
    ) -> VerticalSessionReport:
        """把会话内逐跳评分聚合成 ``VerticalSessionReport``。"""
        severities = [h.get("severity", "none") for h in hop_scores]
        max_score = max((h.get("score", 0.0) for h in hop_scores), default=0.0)
        return VerticalSessionReport(
            session_id=session_id,
            initiator_did=initiator_did,
            intent_revisions=intent_revisions,
            hidden_state=hidden_state,
            hop_scores=hop_scores,
            overall_verdict=overall_verdict_for_severities(severities),
            max_score=max_score,
            total_hops=len(hop_scores),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_revisions(revisions: list[dict]) -> str:
        """把意图流渲染成可读文本供 prompt。"""
        if not revisions:
            return "（尚无意图，这是会话首条）"
        lines = []
        for i, rev in enumerate(revisions):
            goal = rev.get("goal", "")
            constraints = rev.get("constraints", [])
            prohibitions = rev.get("prohibitions", [])
            lines.append(
                f"Δ{i}: goal=\"{goal}\"; constraints={constraints}; prohibitions={prohibitions}"
            )
        return "\n".join(lines)
