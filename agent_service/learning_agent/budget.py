from __future__ import annotations

from dataclasses import dataclass
import time

from agent_service.learning_agent.state import AgentState


class BudgetExceeded(RuntimeError): pass
class DeadlineExceeded(RuntimeError): pass


@dataclass(frozen=True)
class AgentBudget:
    max_nodes: int = 16
    max_retrieval_rounds: int = 2
    max_generation_rounds: int = 2
    max_repairs: int = 1
    max_input_tokens: int = 24000
    max_output_tokens: int = 1600

    def enter(self, state: AgentState, node: str) -> None:
        if time.time() >= state.request.deadlineAt: raise DeadlineExceeded("AGENT_DEADLINE_EXCEEDED")
        if state.node_count >= self.max_nodes: raise BudgetExceeded("AGENT_NODE_BUDGET_EXCEEDED")
        if state.input_tokens > self.max_input_tokens or state.output_tokens > self.max_output_tokens:
            raise BudgetExceeded("AGENT_TOKEN_BUDGET_EXCEEDED")
        state.node_count += 1
        state.trace.append({"node": node, "at": time.time()})

    def allow_retrieval(self, state: AgentState) -> bool:
        return state.retrieval_round < self.max_retrieval_rounds

    def allow_repair(self, state: AgentState) -> bool:
        return state.repair_round < self.max_repairs
