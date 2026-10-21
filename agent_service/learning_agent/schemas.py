from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AgentMode = Literal[
    "QA", "TUTORING", "NOTES", "KEY_POINTS",
    "REVIEW", "PRACTICE", "MOCK_EXAM",
]
RunStatus = Literal["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT", "BUDGET_EXCEEDED"]


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class LearningMemory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["PREFERENCE", "WEAKNESS", "MASTERY", "LEARNING_GOAL"]
    content: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0.0, le=1.0)
    userConfirmed: bool = False


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["1"] = "1"
    runId: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    conversationId: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    userId: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    courseId: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    mode: AgentMode = "QA"
    question: str = Field(min_length=1, max_length=4000)
    authorizedResourceIds: list[str] = Field(max_length=200)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=20)
    memories: list[LearningMemory] = Field(default_factory=list, max_length=20)
    deadlineAt: float

    @field_validator("question")
    @classmethod
    def question_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value: raise ValueError("question must not be blank")
        return value

    @field_validator("authorizedResourceIds")
    @classmethod
    def resources_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)): raise ValueError("authorizedResourceIds must be unique")
        return value


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sourceId: str = Field(pattern=r"^S[1-9][0-9]*$")
    resourceId: str
    indexRevision: str
    chunkId: str
    parentId: str | None = None
    contentHash: str
    titlePath: list[str] = Field(default_factory=list)
    content: str
    locators: list[dict[str, Any]] = Field(default_factory=list)
    score: float = 0.0


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    text: str
    citationIds: list[str] = Field(default_factory=list)


class PracticeOption(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[A-H]$")
    text: str = Field(min_length=1, max_length=500)


class PracticeQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["SINGLE_CHOICE", "TRUE_FALSE", "SHORT_ANSWER"]
    stem: str = Field(min_length=1, max_length=1200)
    options: list[PracticeOption] = Field(default_factory=list, max_length=8)
    correctAnswers: list[str] = Field(min_length=1, max_length=4)
    explanation: str = Field(min_length=1, max_length=2000)
    rubricKeywords: list[str] = Field(default_factory=list, max_length=8)
    difficulty: Literal["EASY", "MEDIUM", "HARD"]
    points: int = Field(ge=1, le=20)
    knowledgePoints: list[str] = Field(min_length=1, max_length=4)
    citationIds: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_question_contract(self):
        option_ids = [item.id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("practice option ids must be unique")
        if self.type == "SINGLE_CHOICE":
            if len(self.options) < 2 or len(self.correctAnswers) != 1:
                raise ValueError("single choice requires options and one answer")
            if self.correctAnswers[0] not in option_ids:
                raise ValueError("single choice answer must reference an option")
        elif self.type == "TRUE_FALSE":
            if option_ids != ["A", "B"] or len(self.correctAnswers) != 1:
                raise ValueError("true/false requires A and B options and one answer")
            if self.correctAnswers[0] not in option_ids:
                raise ValueError("true/false answer must reference an option")
        elif self.options:
            raise ValueError("short answer must not contain options")
        if self.type == "SHORT_ANSWER" and not self.rubricKeywords:
            raise ValueError("short answer requires rubric keywords")
        return self


class PracticeArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=200)
    instructions: str = Field(min_length=1, max_length=1000)
    questions: list[PracticeQuestion] = Field(min_length=1, max_length=12)


class GeneratedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str
    claims: list[Claim] = Field(default_factory=list)
    insufficientEvidence: bool = False
    followUpQuestion: str | None = None
    practice: PracticeArtifact | None = None


class CriticResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    passed: bool
    missingAspects: list[str] = Field(default_factory=list)
    unsupportedClaims: list[str] = Field(default_factory=list)
    needsRetrieval: bool = False
    additionalQueries: list[str] = Field(default_factory=list, max_length=3)


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    inputTokens: int = Field(default=0, ge=0)
    outputTokens: int = Field(default=0, ge=0)
    model: str = ""


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["1"] = "1"
    runId: str
    status: RunStatus
    answer: str = ""
    knowledgeSnapshotId: str = "empty"
    citations: list[Evidence] = Field(default_factory=list)
    practice: PracticeArtifact | None = None
    usage: Usage = Field(default_factory=Usage)
    errorCode: str | None = None
