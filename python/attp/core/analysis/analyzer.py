"""LLM-based semantic taint analyzer."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from attp.app.logging import get_logger
from attp.core.analysis.models import (
    EvidenceItem,
    IntentDescriptor,
    NodeBehaviorProfile,
    NodeTaintVerdict,
    TaintReport,
)
from attp.core.analysis.prompts import INTENT_EXTRACTION_PROMPT, ANALYSIS_PROMPT

logger = get_logger("Analysis")


class SemanticTaintAnalyzer:
    """Analyzes behavior traces using LLM for semantic taint detection."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
    ):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def extract_intent(self, original_task: str) -> IntentDescriptor | None:
        """Extract structured intent from user's original task via LLM."""
        prompt = INTENT_EXTRACTION_PROMPT.format(original_task=original_task)
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": "你是一个安全审计助手，只输出 JSON，不输出任何其他内容。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            data = json.loads(content)
            return IntentDescriptor(
                original_task=original_task,
                core_objective=data.get("core_objective", ""),
                constraints=data.get("constraints", []),
                involved_capabilities=data.get("involved_capabilities", []),
                risk_level=data.get("risk_level", "medium"),
            )
        except Exception as e:
            logger.error("Intent extraction failed: {}", e)
            return None

    async def analyze(
        self,
        session_id: str,
        batch_index: int,
        from_trace_id: int,
        to_trace_id: int,
        traces: list[dict],
        intent: IntentDescriptor,
        previous_context: str = "",
    ) -> TaintReport:
        """Run semantic taint analysis on a batch of behavior traces."""
        profiles = self._reconstruct_profiles(traces)
        if not profiles:
            return TaintReport(
                session_id=session_id,
                batch_index=batch_index,
                from_trace_id=from_trace_id,
                to_trace_id=to_trace_id,
            )

        flow_graph = self._build_flow_graph(profiles)
        behaviors_str = self._format_behaviors(profiles)
        prompt = ANALYSIS_PROMPT.format(
            intent=json.dumps(intent.to_dict(), ensure_ascii=False, indent=2),
            context=previous_context or "（首次分析，无前序上下文）",
            behaviors=behaviors_str,
            flow_graph=flow_graph,
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
            )
            content = response.choices[0].message.content
            result = json.loads(content)

            verdicts = []
            for v in result.get("node_verdicts", []):
                evidence_text = v.get("evidence", "")
                evidence_items = []
                for ref in v.get("evidence_refs", []):
                    evidence_items.append(EvidenceItem(
                        description=ref.get("reason", evidence_text),
                        trace_ids=[ref.get("trace_id", 0)],
                    ))
                verdicts.append(NodeTaintVerdict(
                    node_did=v.get("node_did", ""),
                    hop_count=v.get("hop_count", 0),
                    aligned=v.get("aligned", True),
                    deviation_type=v.get("deviation_type", "none"),
                    influence_detected=v.get("influence_detected", False),
                    influence_type=v.get("influence_type", "none"),
                    evidence=evidence_text,
                    evidence_items=evidence_items,
                    severity=v.get("severity", "none"),
                    taint_score=v.get("taint_score", 0.0),
                ))

            return TaintReport(
                session_id=session_id,
                batch_index=batch_index,
                from_trace_id=from_trace_id,
                to_trace_id=to_trace_id,
                node_verdicts=verdicts,
                overall_verdict=result.get("overall_verdict", "clean"),
                summary=result.get("summary", ""),
                context_summary=result.get("context_summary", ""),
            )
        except Exception as e:
            logger.error("LLM analysis failed: {}", e)
            return TaintReport(
                session_id=session_id,
                batch_index=batch_index,
                from_trace_id=from_trace_id,
                to_trace_id=to_trace_id,
                summary=f"Analysis failed: {e}",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reconstruct_profiles(self, traces: list[dict]) -> list[NodeBehaviorProfile]:
        """Group traces by (node_did, hop_count) into behavior profiles."""
        profiles_map: dict[tuple[str, int], NodeBehaviorProfile] = {}
        for row in traces:
            key = (row["node_did"], row["hop_count"])
            if key not in profiles_map:
                profiles_map[key] = NodeBehaviorProfile(
                    node_did=row["node_did"],
                    hop_count=row["hop_count"],
                )
            profile = profiles_map[key]
            entry = {
                "id": row.get("id", 0),
                "content": row.get("content", ""),
                "target": row.get("target", ""),
                "timestamp": row.get("timestamp"),
            }
            ft = row["field_type"]
            if ft == "a":
                profile.field_a.append(entry)
            elif ft == "b":
                profile.field_b.append(entry)
            elif ft == "d":
                profile.field_d.append(entry)
        return sorted(profiles_map.values(), key=lambda p: p.hop_count)

    def _build_flow_graph(self, profiles: list[NodeBehaviorProfile]) -> str:
        """Build a human-readable message flow graph."""
        lines = []
        for p in profiles:
            node = p.node_did.split(":")[-1] if ":" in p.node_did else p.node_did
            for d in p.field_d:
                target = d.get("target", "")
                target_short = target.split(":")[-1] if ":" in target else target
                lines.append(f"Node [{node}] (hop={p.hop_count}) --(d, trace#{d.get('id', '?')})--> Node [{target_short}]")
        return "\n".join(lines) if lines else "无节点间消息传递"

    def _format_behaviors(self, profiles: list[NodeBehaviorProfile]) -> str:
        """Format behavior profiles for the LLM prompt."""
        parts = []
        for p in profiles:
            section = f"### 节点: {p.node_did} (hop={p.hop_count})\n"
            if p.field_a:
                section += "**Agent->Tool 调用:**\n"
                for a in p.field_a:
                    section += f'  - [trace#{a["id"]}] 目标: {a["target"]}, 内容: {a["content"][:300]}\n'
            if p.field_b:
                section += "**Agent->User 回复:**\n"
                for b in p.field_b:
                    section += f'  - [trace#{b["id"]}] 内容: {b["content"][:300]}\n'
            if p.field_d:
                section += "**Agent->Agent 消息:**\n"
                for d in p.field_d:
                    section += f'  - [trace#{d["id"]}] 目标: {d["target"]}, 内容: {d["content"][:300]}\n'
            parts.append(section)
        return "\n".join(parts)
