import uuid
from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    nickname: Mapped[str] = mapped_column(String(50))
    avatar: Mapped[str | None] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(20), default="USER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    username: Mapped[str] = mapped_column(String(32), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class Course(Base):
    __tablename__ = "courses"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    semester: Mapped[str] = mapped_column(String(50), default="")
    description: Mapped[str] = mapped_column(String(1000), default="")
    created_by: Mapped[uuid.UUID] = mapped_column("owner_id", ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class LegacyStudyRecord(Base):
    __tablename__ = "legacy_study_records"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    payload: Mapped[dict] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

class CourseChapter(Base):
    __tablename__ = "course_chapters"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("course_id", "sort_order"),)

class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(255))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ResourceVersion(Base):
    __tablename__ = "resource_versions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    content_type: Mapped[str] = mapped_column(String(150))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    checksum_sha256: Mapped[str | None] = mapped_column(String(64))
    object_version_id: Mapped[str | None] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(24), default="UPLOADED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("resource_id", "version_no"),)

class CourseResource(Base):
    __tablename__ = "course_resources"
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("course_chapters.id", ondelete="SET NULL"))
    added_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class UploadSession(Base):
    __tablename__ = "upload_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    chapter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("course_chapters.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255))
    object_version_id: Mapped[str | None] = mapped_column(String(200))
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str] = mapped_column(String(150))
    expected_size: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    state: Mapped[str] = mapped_column(String(20), default="PENDING")
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resources.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)

class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    resource_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resource_versions.id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(20), default="QUEUED", index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class KnowledgeIndex(Base):
    __tablename__ = 'knowledge_indexes'
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('resources.id', ondelete='CASCADE'), index=True)
    resource_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('resource_versions.id', ondelete='CASCADE'))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('processing_jobs.id', ondelete='CASCADE'), index=True)
    collection: Mapped[str] = mapped_column(String(100))
    config: Mapped[dict] = mapped_column(JSONB)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(20), default='BUILDING')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ActiveKnowledgeIndex(Base):
    __tablename__ = 'active_knowledge_indexes'
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('resources.id', ondelete='CASCADE'), primary_key=True)
    index_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('knowledge_indexes.id'))

class AgentThread(Base):
    __tablename__='agent_threads'
    history_summary:Mapped[dict]=mapped_column(JSONB,server_default='{}')
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id'),index=True)
    course_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('courses.id'),index=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class AgentRun(Base):
    __tablename__='agent_runs'
    claim_attempts:Mapped[int]=mapped_column(Integer,default=0,server_default='0')
    max_claim_attempts:Mapped[int]=mapped_column(Integer,default=3,server_default='3')
    started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    deadline_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    request_id:Mapped[str|None]=mapped_column(String(36))
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    thread_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('agent_threads.id'),index=True)
    state:Mapped[str]=mapped_column(String(20),default='QUEUED')
    input_text:Mapped[str]=mapped_column(Text)
    model_id:Mapped[str|None]=mapped_column(String(100))
    checkpoint:Mapped[dict]=mapped_column(JSONB,default=dict)
    answer:Mapped[str]=mapped_column(Text,default='')
    usage:Mapped[dict]=mapped_column(JSONB,default=dict)
    lease_token:Mapped[str|None]=mapped_column(String(36))
    lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    cancel_requested:Mapped[bool]=mapped_column(Boolean,default=False)
    error_code:Mapped[str|None]=mapped_column(String(80))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class AgentEvent(Base):
    __tablename__='agent_events'
    id:Mapped[int]=mapped_column(BigInteger,primary_key=True,autoincrement=True)
    run_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('agent_runs.id'),index=True)
    kind:Mapped[str]=mapped_column(String(40))
    data:Mapped[dict]=mapped_column(JSONB,default=dict)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())

class LearningPreference(Base):
    __tablename__='learning_preferences'
    user_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id'),primary_key=True)
    key:Mapped[str]=mapped_column(String(50),primary_key=True)
    value:Mapped[str]=mapped_column(String(300))
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())

class LearningMemory(Base):
    __tablename__='learning_memories'
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id'),index=True)
    course_id:Mapped[uuid.UUID|None]=mapped_column(ForeignKey('courses.id',ondelete='CASCADE'),index=True)
    kind:Mapped[str]=mapped_column(String(30))
    status:Mapped[str]=mapped_column(String(12),server_default='confirmed')
    content:Mapped[str]=mapped_column(String(500))
    source_run_id:Mapped[uuid.UUID|None]=mapped_column(ForeignKey('agent_runs.id'))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
    fact_key:Mapped[str|None]=mapped_column(String(100),index=True)
    revision:Mapped[int]=mapped_column(Integer,default=1,server_default='1')
    origin:Mapped[dict]=mapped_column(JSONB,default=dict,server_default='{}')
    updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now(),onupdate=func.now())

class PracticeQuestion(Base):
    __tablename__='practice_questions'
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True)
    run_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('agent_runs.id'),index=True)
    question:Mapped[str]=mapped_column(Text)
    expected_answer:Mapped[str]=mapped_column(Text)
    evidence:Mapped[list]=mapped_column(JSONB)
    rubric:Mapped[list]=mapped_column(JSONB,server_default='[]')

class PracticeAttempt(Base):
    __tablename__='practice_attempts'
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4)
    user_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('users.id'),index=True)
    course_id:Mapped[uuid.UUID]=mapped_column(ForeignKey('courses.id',ondelete='CASCADE'),index=True)
    question:Mapped[str]=mapped_column(Text)
    question_id:Mapped[uuid.UUID|None]=mapped_column(ForeignKey('practice_questions.id'))
    expected_answer:Mapped[str]=mapped_column(Text)
    submitted_answer:Mapped[str]=mapped_column(Text)
    correct:Mapped[bool]=mapped_column(Boolean)
    feedback:Mapped[dict]=mapped_column(JSONB,server_default='{}')
    source_ids:Mapped[list]=mapped_column(JSONB,default=list)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=func.now())
