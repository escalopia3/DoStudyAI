import uuid
from pydantic import BaseModel, ConfigDict, Field

class RegisterInput(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(default='', max_length=50)

class LoginInput(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=1, max_length=128)

class CourseInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    semester: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=1000)

class ChapterInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)

class UploadInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(alias="contentType", min_length=1, max_length=150)
    size_bytes: int = Field(alias="sizeBytes", gt=0, le=20 * 1024 * 1024 * 1024)
    chapter_id: uuid.UUID | None = Field(default=None, alias="chapterId")
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

class ImportInput(UploadInput):
    url: str = Field(min_length=8, max_length=2048)
