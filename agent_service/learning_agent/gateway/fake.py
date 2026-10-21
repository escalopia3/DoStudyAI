from __future__ import annotations

from typing import Sequence

from agent_service.learning_agent.schemas import (Claim, CriticResult, Evidence, GeneratedAnswer,
    HistoryMessage, PracticeArtifact, PracticeOption, PracticeQuestion)


class FakeLearningLlmGateway:
    """Deterministic offline gateway used for workflow and contract tests."""
    model_name = "fake-learning-llm"

    def rewrite_question(self, question: str, history: Sequence[HistoryMessage]) -> str:
        return question.strip()

    def plan_queries(self, question: str, mode: str) -> list[str]:
        return [question.strip()]

    def generate(self, mode: str, question: str, context: str,
                 evidence: Sequence[Evidence]) -> GeneratedAnswer:
        if not evidence:
            return GeneratedAnswer(answer="当前课程资料中没有找到足够证据回答这个问题。",
                                   insufficientEvidence=True)
        first = evidence[0]
        answer = f"根据当前课程资料，{first.content[:180]} [{first.sourceId}]"
        if mode == "TUTORING":
            answer += "\n\n理解检查：请尝试用自己的话概括上面的核心概念。"
        practice = None
        if mode == "PRACTICE":
            practice = PracticeArtifact(title="课程练习", instructions="完成后提交查看解析。", questions=[
                PracticeQuestion(type="SINGLE_CHOICE", stem="课程资料指出的核心结论是什么？",
                    options=[PracticeOption(id="A", text=first.content[:60]), PracticeOption(id="B", text="资料未提及的结论")],
                    correctAnswers=["A"], explanation=first.content[:120], difficulty="EASY", points=5,
                    knowledgePoints=[first.titlePath[-1] if first.titlePath else "课程知识"], citationIds=[first.sourceId]),
                PracticeQuestion(type="SHORT_ANSWER", stem="请概括这段资料的核心含义。", options=[],
                    correctAnswers=[first.content[:120]], explanation=first.content[:120],
                    rubricKeywords=[word for word in (first.titlePath[-1:] or ["核心概念"])],
                    difficulty="MEDIUM", points=10,
                    knowledgePoints=[first.titlePath[-1] if first.titlePath else "课程知识"], citationIds=[first.sourceId])])
        return GeneratedAnswer(answer=answer,
            claims=[Claim(text=first.content[:120], citationIds=[first.sourceId])],
            followUpQuestion="你希望我换一种方式继续讲解吗？", practice=practice)

    def critique(self, question: str, answer: GeneratedAnswer,
                 evidence: Sequence[Evidence]) -> CriticResult:
        valid = {item.sourceId for item in evidence}
        unsupported = [claim.text for claim in answer.claims
                       if not claim.citationIds or any(x not in valid for x in claim.citationIds)]
        return CriticResult(passed=not unsupported, unsupportedClaims=unsupported)

    def repair(self, mode: str, question: str, answer: GeneratedAnswer, critic: CriticResult,
               context: str, evidence: Sequence[Evidence]) -> GeneratedAnswer:
        return self.generate(mode, question, context, evidence)
