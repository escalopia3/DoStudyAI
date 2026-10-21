from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_service.learning_agent.schemas import AgentRunRequest, CriticResult, Evidence, GeneratedAnswer


@dataclass
class AgentState:
    request: AgentRunRequest
    standalone_question: str = ""
    retrieval_queries: list[str] = field(default_factory=list)
    knowledge_snapshot_id: str = "empty"
    evidence: list[Evidence] = field(default_factory=list)
    context: str = ""
    draft: GeneratedAnswer | None = None
    critic: CriticResult | None = None
    retrieval_round: int = 0
    generation_round: int = 0
    repair_round: int = 0
    node_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error_code: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
