from __future__ import annotations

from dataclasses import asdict
from typing import Callable

from agent_service.learning_agent.budget import AgentBudget
from agent_service.learning_agent.context import CitationValidator, ContextBuilder, estimate_tokens
from agent_service.learning_agent.gateway.base import LearningLlmGateway
from agent_service.learning_agent.schemas import AgentRunResult, CriticResult, Usage
from agent_service.learning_agent.prompts import MEMORY_BOUNDARY
from agent_service.learning_agent.state import AgentState
from knowledge_service.retrieval.service import EvidenceRetriever


class LearningAgentGraph:
    """Node implementation shared by LangGraph runtime and deterministic tests."""
    def __init__(self, gateway: LearningLlmGateway, retriever: EvidenceRetriever,
                 budget: AgentBudget | None = None, context_builder: ContextBuilder | None = None,
                 cancelled: Callable[[str], bool] | None = None):
        self.gateway, self.retriever = gateway, retriever
        self.budget = budget or AgentBudget()
        self.context_builder = context_builder or ContextBuilder()
        self.citations = CitationValidator()
        self.cancelled = cancelled or (lambda _run_id: False)

    def _enter(self, state: AgentState, node: str) -> None:
        if self.cancelled(state.request.runId): raise RuntimeError("RUN_CANCELLED")
        self.budget.enter(state, node)

    def resolve(self, state: AgentState) -> AgentState:
        self._enter(state, "resolve_question")
        state.standalone_question = self.gateway.rewrite_question(
            state.request.question, state.request.history)
        return state

    def plan(self, state: AgentState) -> AgentState:
        self._enter(state, "plan_retrieval")
        if state.critic and state.critic.additionalQueries:
            state.retrieval_queries = state.critic.additionalQueries[:3]
        else:
            state.retrieval_queries = self.gateway.plan_queries(
                state.standalone_question, state.request.mode)
        return state

    def retrieve(self, state: AgentState) -> AgentState:
        self._enter(state, "retrieve")
        if not self.budget.allow_retrieval(state): raise RuntimeError("RETRIEVAL_ROUND_LIMIT")
        snapshot, found = self.retriever.search(state.request.userId,
            state.request.authorizedResourceIds, state.retrieval_queries)
        state.retrieval_round += 1
        state.knowledge_snapshot_id = snapshot
        by_id = {(x.resourceId, x.indexRevision, x.chunkId): x for x in state.evidence}
        for item in found: by_id.setdefault((item.resourceId, item.indexRevision, item.chunkId), item)
        state.evidence = sorted(by_id.values(), key=lambda x: x.score, reverse=True)
        return state

    def build_context(self, state: AgentState) -> AgentState:
        self._enter(state, "build_context")
        built = self.context_builder.build(state.evidence)
        state.context, state.evidence = built.text, built.evidence
        if state.request.memories:
            memory_text = "\n".join(
                f"- {item.type}: {item.content}（置信度 {item.confidence:.2f}）"
                for item in state.request.memories)
            state.context += f"\n\n{MEMORY_BOUNDARY}\n{memory_text}"
        state.input_tokens += built.estimated_tokens + estimate_tokens(state.standalone_question)
        if state.request.memories: state.input_tokens += estimate_tokens(memory_text)
        return state

    def generate(self, state: AgentState) -> AgentState:
        self._enter(state, "generate")
        if state.generation_round >= self.budget.max_generation_rounds:
            raise RuntimeError("GENERATION_ROUND_LIMIT")
        state.draft = self.gateway.generate(state.request.mode, state.standalone_question,
                                             state.context, state.evidence)
        state.generation_round += 1
        state.output_tokens += estimate_tokens(state.draft.model_dump_json())
        return state

    def validate(self, state: AgentState) -> AgentState:
        self._enter(state, "verify_citations")
        if not state.draft: raise RuntimeError("MISSING_DRAFT")
        self.citations.validate(state.draft, state.evidence)
        return state

    def critique(self, state: AgentState) -> AgentState:
        self._enter(state, "critic")
        if not state.draft: raise RuntimeError("MISSING_DRAFT")
        state.critic = self.gateway.critique(state.standalone_question, state.draft, state.evidence)
        return state

    def route_after_critic(self, state: AgentState) -> str:
        critic = state.critic or CriticResult(passed=True)
        if critic.passed: return "finalize"
        if critic.needsRetrieval and critic.additionalQueries and self.budget.allow_retrieval(state):
            return "plan"
        if self.budget.allow_repair(state): return "repair"
        return "finalize_insufficient"

    def repair(self, state: AgentState) -> AgentState:
        self._enter(state, "repair")
        if not state.draft or not state.critic: raise RuntimeError("MISSING_REPAIR_INPUT")
        state.draft = self.gateway.repair(state.request.mode, state.standalone_question, state.draft, state.critic,
                                          state.context, state.evidence)
        state.repair_round += 1
        state.output_tokens += estimate_tokens(state.draft.answer)
        return state

    def result(self, state: AgentState, insufficient: bool = False) -> AgentRunResult:
        self._enter(state, "finalize")
        if not state.draft: raise RuntimeError("MISSING_DRAFT")
        if insufficient and not state.draft.insufficientEvidence:
            state.draft = state.draft.model_copy(update={
                "answer": "当前课程资料不足以可靠完成回答，请补充资料或缩小问题范围。",
                "insufficientEvidence": True, "claims": [], "practice": None})
        used = self.citations.validate(state.draft, state.evidence)
        return AgentRunResult(runId=state.request.runId, status="COMPLETED",
            answer=state.draft.answer, knowledgeSnapshotId=state.knowledge_snapshot_id,
            citations=used, practice=state.draft.practice,
            usage=Usage(inputTokens=state.input_tokens,
                outputTokens=state.output_tokens, model=self.gateway.model_name))

    def run_deterministic(self, state: AgentState) -> AgentRunResult:
        """Same bounded transitions as LangGraph, usable before dependency installation."""
        self.resolve(state); self.plan(state); self.retrieve(state); self.build_context(state)
        self.generate(state); self.validate(state); self.critique(state)
        while True:
            route = self.route_after_critic(state)
            if route == "finalize": return self.result(state)
            if route == "finalize_insufficient": return self.result(state, True)
            if route == "plan":
                self.plan(state); self.retrieve(state); self.build_context(state)
                self.generate(state); self.validate(state); self.critique(state)
            elif route == "repair":
                self.repair(state); self.validate(state); self.critique(state)

    def compile(self):
        """Build the production LangGraph lazily; importing the project stays offline."""
        try:
            from langgraph.graph import END, StateGraph
        except ImportError as exc:
            raise RuntimeError("langgraph is required to run the production learning agent") from exc
        graph = StateGraph(AgentState)
        for name, node in (("resolve", self.resolve), ("plan", self.plan),
                           ("retrieve", self.retrieve), ("context", self.build_context),
                           ("generate", self.generate), ("validate", self.validate),
                           ("critic", self.critique), ("repair", self.repair)):
            graph.add_node(name, node)
        graph.set_entry_point("resolve")
        graph.add_edge("resolve", "plan"); graph.add_edge("plan", "retrieve")
        graph.add_edge("retrieve", "context"); graph.add_edge("context", "generate")
        graph.add_edge("generate", "validate"); graph.add_edge("validate", "critic")
        graph.add_conditional_edges("critic", self.route_after_critic,
            {"plan": "plan", "repair": "repair", "finalize": END, "finalize_insufficient": END})
        graph.add_edge("repair", "validate")
        return graph.compile()
