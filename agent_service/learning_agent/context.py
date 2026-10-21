from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from agent_service.learning_agent.schemas import Evidence, GeneratedAnswer


def estimate_tokens(text: str) -> int:
    """Conservative dependency-free estimate; provider usage replaces it later."""
    chinese = len(re.findall(r"[\u3400-\u9fff]", text))
    other = max(0, len(text) - chinese)
    return chinese + (other + 3) // 4


@dataclass(frozen=True)
class ContextBuildResult:
    text: str
    evidence: list[Evidence]
    estimated_tokens: int


class ContextBuilder:
    def __init__(self, max_evidence_tokens: int = 12000, max_items: int = 8):
        self.max_evidence_tokens, self.max_items = max_evidence_tokens, max_items

    def build(self, candidates: Iterable[Evidence]) -> ContextBuildResult:
        selected, seen, used = [], set(), 0
        for item in candidates:
            identity = (item.resourceId, item.indexRevision, item.chunkId)
            if identity in seen: continue
            cost = estimate_tokens(item.content) + estimate_tokens(" / ".join(item.titlePath)) + 20
            if selected and used + cost > self.max_evidence_tokens: continue
            selected.append(item.model_copy(update={"sourceId": f"S{len(selected)+1}"}))
            seen.add(identity); used += cost
            if len(selected) >= self.max_items: break
        text = "\n\n".join(f"[{x.sourceId}] 章节：{' / '.join(x.titlePath) or '未分类'}\n{x.content}"
                            for x in selected)
        return ContextBuildResult(text, selected, estimate_tokens(text))


class CitationValidator:
    def validate(self, answer: GeneratedAnswer, evidence: list[Evidence]) -> list[Evidence]:
        registry = {item.sourceId: item for item in evidence}
        used = []
        for claim in answer.claims:
            if not claim.citationIds and not answer.insufficientEvidence:
                raise ValueError("CLAIM_WITHOUT_CITATION")
            for source_id in claim.citationIds:
                if source_id not in registry: raise ValueError("UNKNOWN_CITATION")
                if registry[source_id] not in used: used.append(registry[source_id])
        if answer.practice:
            for question in answer.practice.questions:
                for source_id in question.citationIds:
                    if source_id not in registry: raise ValueError("UNKNOWN_PRACTICE_CITATION")
                    if registry[source_id] not in used: used.append(registry[source_id])
        if not answer.insufficientEvidence and evidence and not used:
            raise ValueError("ANSWER_WITHOUT_CITATION")
        return used
