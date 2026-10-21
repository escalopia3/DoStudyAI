from __future__ import annotations

import os
import time
import unittest

from sqlalchemy import create_engine, select

from agent_service.learning_agent.budget import AgentBudget, BudgetExceeded, DeadlineExceeded
from agent_service.learning_agent.gateway.fake import FakeLearningLlmGateway
from agent_service.learning_agent.gateway.openai_compatible import (
    LlmConfigurationError,
    OpenAiCompatibleLearningGateway,
)
from agent_service.learning_agent.prompts import MODE_PROMPTS
from agent_service.learning_agent.graph import LearningAgentGraph
from agent_service.learning_agent.persistence import (
    AgentRunConflict,
    AgentRunStore,
    agent_events,
    agent_runs,
)
from agent_service.learning_agent.schemas import (
    AgentRunRequest,
    Claim,
    CriticResult,
    Evidence,
    GeneratedAnswer,
    PracticeQuestion,
)
from agent_service.learning_agent.state import AgentState
from agent_service.store import metadata


def request(**changes) -> AgentRunRequest:
    values = {
        "runId": "run_12345678",
        "conversationId": "conversation_12345678",
        "userId": "1",
        "courseId": "2",
        "question": "B+树为什么适合数据库索引？",
        "authorizedResourceIds": ["10"],
        "deadlineAt": time.time() + 60,
    }
    values.update(changes)
    return AgentRunRequest(**values)


def evidence(source_id: str = "S1") -> Evidence:
    return Evidence(
        sourceId=source_id,
        resourceId="10",
        indexRevision="r1",
        chunkId="child-1",
        parentId="parent-1",
        contentHash="sha256:abc",
        titlePath=["数据库", "B+树"],
        content="B+树具有较高的扇出，能够减少磁盘随机访问次数。",
        locators=[{"page": 12, "startMs": 31000, "endMs": 45000}],
        score=0.9,
    )


class StaticRetriever:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.calls = 0

    def search(self, owner_id, authorized_resource_ids, queries):
        self.calls += 1
        if owner_id != "1" or authorized_resource_ids != ["10"]:
            raise AssertionError("authorization scope changed inside agent")
        return "snapshot-1", self.items


class FabricatingGateway(FakeLearningLlmGateway):
    def generate(self, mode, question, context, items):
        return GeneratedAnswer(
            answer="这是一个没有来源的结论 [S99]",
            claims=[Claim(text="没有来源的结论", citationIds=["S99"])],
        )


class AlwaysRepairGateway(FakeLearningLlmGateway):
    def critique(self, question, answer, items):
        return CriticResult(passed=False, missingAspects=["still incomplete"])


class RepairModeGateway(AlwaysRepairGateway):
    def __init__(self):
        self.repair_modes = []

    def repair(self, mode, question, answer, critic, context, items):
        self.repair_modes.append(mode)
        return super().repair(mode, question, answer, critic, context, items)


class LearningAgentGraphTests(unittest.TestCase):
    def test_answer_keeps_locator_and_active_revision_evidence(self):
        graph = LearningAgentGraph(FakeLearningLlmGateway(), StaticRetriever([evidence()]))
        result = graph.run_deterministic(AgentState(request()))
        self.assertEqual("COMPLETED", result.status)
        self.assertEqual("snapshot-1", result.knowledgeSnapshotId)
        self.assertEqual(1, len(result.citations))
        self.assertEqual("r1", result.citations[0].indexRevision)
        self.assertEqual(12, result.citations[0].locators[0]["page"])
        self.assertIn("[S1]", result.answer)

    def test_no_evidence_fails_closed_instead_of_guessing(self):
        result = LearningAgentGraph(
            FakeLearningLlmGateway(), StaticRetriever()
        ).run_deterministic(AgentState(request()))
        self.assertEqual("COMPLETED", result.status)
        self.assertEqual([], result.citations)
        self.assertIn("没有找到足够证据", result.answer)

    def test_unknown_citation_is_rejected_before_critic(self):
        graph = LearningAgentGraph(FabricatingGateway(), StaticRetriever([evidence()]))
        with self.assertRaisesRegex(ValueError, "UNKNOWN_CITATION"):
            graph.run_deterministic(AgentState(request()))

    def test_repair_round_is_bounded_and_degrades_to_insufficient(self):
        state = AgentState(request())
        graph = LearningAgentGraph(AlwaysRepairGateway(), StaticRetriever([evidence()]))
        result = graph.run_deterministic(state)
        self.assertTrue(result.answer.startswith("当前课程资料不足"))
        self.assertEqual(1, state.repair_round)
        self.assertLessEqual(state.node_count, graph.budget.max_nodes)

    def test_revision_preserves_specialized_mode(self):
        gateway = RepairModeGateway()
        state = AgentState(request(mode="MOCK_EXAM"))
        LearningAgentGraph(gateway, StaticRetriever([evidence()])).run_deterministic(state)
        self.assertEqual(["MOCK_EXAM"], gateway.repair_modes)

    def test_revision_and_practice_modes_have_explicit_boundaries(self):
        self.assertIn("资料证据不足", MODE_PROMPTS["REVIEW"])
        self.assertIn("不得考查证据未覆盖", MODE_PROMPTS["PRACTICE"])
        self.assertIn("不代表真实考试范围", MODE_PROMPTS["MOCK_EXAM"])

    def test_practice_mode_returns_structured_questions_with_evidence(self):
        result = LearningAgentGraph(
            FakeLearningLlmGateway(), StaticRetriever([evidence()])
        ).run_deterministic(AgentState(request(mode="PRACTICE")))
        self.assertIsNotNone(result.practice)
        self.assertEqual(2, len(result.practice.questions))
        self.assertEqual(["S1"], result.practice.questions[0].citationIds)

    def test_practice_schema_rejects_answer_outside_options(self):
        with self.assertRaisesRegex(ValueError, "answer must reference an option"):
            PracticeQuestion(
                type="SINGLE_CHOICE", stem="题目", options=[
                    {"id": "A", "text": "甲"}, {"id": "B", "text": "乙"}],
                correctAnswers=["C"], explanation="解析", rubricKeywords=[],
                difficulty="EASY", points=2, knowledgePoints=["知识点"], citationIds=["S1"],
            )

    def test_expired_request_never_calls_model(self):
        state = AgentState(request(deadlineAt=time.time() - 1))
        with self.assertRaises(DeadlineExceeded):
            LearningAgentGraph(FakeLearningLlmGateway(), StaticRetriever()).run_deterministic(state)

    def test_token_budget_stops_at_next_boundary(self):
        state = AgentState(request())
        graph = LearningAgentGraph(
            FakeLearningLlmGateway(),
            StaticRetriever([evidence()]),
            budget=AgentBudget(max_input_tokens=1),
        )
        with self.assertRaises(BudgetExceeded):
            graph.run_deterministic(state)


class LearningAgentStoreTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        metadata.create_all(self.engine, tables=[agent_runs, agent_events])
        self.store = AgentRunStore(self.engine)

    def test_submit_is_idempotent_and_conflict_is_detected(self):
        original = request()
        self.store.submit(original)
        self.store.submit(original)
        with self.engine.connect() as db:
            self.assertEqual(1, len(db.execute(select(agent_runs)).all()))
            self.assertEqual(1, len(db.execute(select(agent_events)).all()))
        with self.assertRaises(AgentRunConflict):
            self.store.submit(request(question="另一个问题"))

    def test_claim_finish_and_outbox_are_fenced(self):
        self.store.submit(request())
        claimed = self.store.claim(lease_seconds=30)
        self.assertEqual("RUNNING", claimed["state"])
        result = LearningAgentGraph(
            FakeLearningLlmGateway(), StaticRetriever([evidence()])
        ).run_deterministic(AgentState(request()))
        self.assertFalse(self.store.finish(claimed["run_id"], claimed["attempt"] + 1,
                                           result, "COMPLETED"))
        self.assertTrue(self.store.finish(claimed["run_id"], claimed["attempt"],
                                          result, "COMPLETED"))
        saved = self.store.get(claimed["run_id"])
        self.assertEqual("COMPLETED", saved["state"])
        with self.engine.connect() as db:
            events = db.execute(select(agent_events).order_by(agent_events.c.sequence)).mappings().all()
        self.assertEqual(["QUEUED", "RUNNING", "COMPLETED"],
                         [__import__("json").loads(x["payload_json"])["state"] for x in events])

    def test_cancel_is_terminal_and_idempotent(self):
        self.store.submit(request())
        first = self.store.cancel("run_12345678")
        second = self.store.cancel("run_12345678")
        self.assertEqual("CANCELLED", first["state"])
        self.assertEqual(first["sequence"], second["sequence"])
        self.assertIsNone(self.store.claim())


class LlmConfigurationTests(unittest.TestCase):
    def test_missing_provider_configuration_fails_without_network(self):
        names = ("LEARNING_LLM_BASE_URL", "LEARNING_LLM_API_KEY", "LEARNING_LLM_MODEL")
        saved = {name: os.environ.pop(name, None) for name in names}
        try:
            with self.assertRaises(LlmConfigurationError):
                OpenAiCompatibleLearningGateway()
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
