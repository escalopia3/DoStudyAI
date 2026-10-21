from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class ParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["1"] = "1"
    jobId: str = Field(pattern=r"^[a-zA-Z0-9_-]{8,64}$")
    resourceId: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    userId: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    courseId: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    sourceRevision: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    sourceType: Literal["PDF", "DOCX", "PPTX", "VIDEO"]


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schemaVersion: Literal["1"] = "1"
    jobId: str
    resourceId: str
    sourceRevision: str
    sequence: int = Field(ge=1)
    state: Literal["QUEUED", "RUNNING", "PARSED", "INDEXING", "READY", "FAILED", "CANCELLED"]
    artifactPrefix: str | None = None
    errorCode: str | None = None
