from __future__ import annotations

import json
import os
from typing import Any, Sequence, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from agent_service.learning_agent.gateway.base import LearningLlmGateway
from agent_service.learning_agent.prompts import BASE_SYSTEM_PROMPT, EVIDENCE_BOUNDARY, MODE_PROMPTS
from agent_service.learning_agent.schemas import CriticResult, Evidence, GeneratedAnswer, HistoryMessage

T = TypeVar("T", bound=BaseModel)


class LlmConfigurationError(RuntimeError): pass
class LlmOutputError(RuntimeError): pass


class OpenAiCompatibleLearningGateway(LearningLlmGateway):
    """Provider-neutral chat-completions client. Secrets are read only from env."""
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or os.getenv("LEARNING_LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.getenv("LEARNING_LLM_API_KEY", "")
        self.model = model or os.getenv("LEARNING_LLM_MODEL", "")
        self.timeout = timeout or float(os.getenv("LEARNING_LLM_TIMEOUT_SECONDS", "45"))
        if not self.base_url or not self.api_key or not self.model:
            raise LlmConfigurationError("LEARNING_LLM_BASE_URL/API_KEY/MODEL must be configured")
        self.http = httpx.Client(base_url=self.base_url, timeout=self.timeout,
            headers={"Authorization": "Bearer " + self.api_key}, trust_env=False)

    @property
    def model_name(self) -> str: return self.model
    def close(self): self.http.close()

    def _json(self, task: str, user: str, schema: type[T]) -> T:
        # DeepSeek and some OpenAI-compatible providers reject json_object unless
        # the prompt explicitly contains the lowercase ASCII word "json".
        structured_task = task + "\nReturn exactly one valid json object and no surrounding prose."
        body = {"model": self.model, "temperature": float(os.getenv("LEARNING_LLM_TEMPERATURE", "0.2")),
            "max_tokens": int(os.getenv("LEARNING_LLM_MAX_OUTPUT_TOKENS", "1600")),
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": BASE_SYSTEM_PROMPT + "\n\n" + structured_task},
                         {"role": "user", "content": user}]}
        thinking = os.getenv("LEARNING_LLM_THINKING", "").strip().lower()
        if thinking:
            if thinking not in {"enabled", "disabled"}:
                raise LlmConfigurationError("LEARNING_LLM_THINKING must be enabled or disabled")
            body["thinking"] = {"type": thinking}
        response = self.http.post("/chat/completions", json=body)
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
            return schema.model_validate_json(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise LlmOutputError("LLM_OUTPUT_INVALID") from exc

    def _text_json(self, task: str, user: str) -> dict[str, Any]:
        class TextResult(BaseModel):
            value: str
        return self._json(task, user, TextResult).model_dump()

    def rewrite_question(self, question: str, history: Sequence[HistoryMessage]) -> str:
        if not history: return question
        history_text = "\n".join(f"{x.role}: {x.content}" for x in history[-6:])
        result = self._text_json("只把当前问题改写为可独立检索的问题，不回答。输出 {\"value\":\"...\"}。",
                                 f"历史：\n{history_text}\n当前问题：{question}")
        return result["value"].strip() or question

    def plan_queries(self, question: str, mode: str) -> list[str]:
        class QueryPlan(BaseModel): queries: list[str]
        result = self._json("生成1到3条简短课程资料检索查询。输出 {\"queries\":[...]}。",
                            f"模式：{mode}\n问题：{question}", QueryPlan)
        return [x.strip() for x in result.queries[:3] if x.strip()] or [question]

    @staticmethod
    def _evidence_text(evidence: Sequence[Evidence]) -> str:
        return "\n\n".join(f"[{x.sourceId}] 章节：{' / '.join(x.titlePath)}\n{x.content}" for x in evidence)

    def generate(self, mode: str, question: str, context: str,
                 evidence: Sequence[Evidence]) -> GeneratedAnswer:
        practice_fields = ", practice{title,instructions,questions[{type,stem,options[{id,text}],correctAnswers,explanation,rubricKeywords,difficulty,points,knowledgePoints,citationIds}]}" if mode == "PRACTICE" else ", practice:null"
        task = MODE_PROMPTS[mode] + f" 输出严格JSON：answer, claims[{{text,citationIds}}], insufficientEvidence, followUpQuestion{practice_fields}。"
        return self._json(task, f"问题：{question}\n\n{EVIDENCE_BOUNDARY}\n{context}", GeneratedAnswer)

    def critique(self, question: str, answer: GeneratedAnswer,
                 evidence: Sequence[Evidence]) -> CriticResult:
        task = "检查回答是否覆盖问题、是否存在无证据结论。输出严格JSON：passed, missingAspects, unsupportedClaims, needsRetrieval, additionalQueries。"
        return self._json(task, f"问题：{question}\n回答：{answer.model_dump_json()}\n证据：{self._evidence_text(evidence)}", CriticResult)

    def repair(self, mode: str, question: str, answer: GeneratedAnswer, critic: CriticResult,
               context: str, evidence: Sequence[Evidence]) -> GeneratedAnswer:
        task = MODE_PROMPTS[mode] + " 根据检查结果仅修正已有回答，保持该模式要求的结构，禁止增加无证据事实。输出 GeneratedAnswer JSON。"
        return self._json(task, f"问题：{question}\n草稿：{answer.model_dump_json()}\n检查：{critic.model_dump_json()}\n{EVIDENCE_BOUNDARY}\n{context}", GeneratedAnswer)
