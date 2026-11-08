"""Direct uploads, immutable resource versions and durable leased jobs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    now = sa.text("CURRENT_TIMESTAMP")
    op.create_table("resources",
        sa.Column("id", uuid, primary_key=True), sa.Column("owner_id", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("current_version_id", uuid), sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("kind IN ('PDF','PPTX','DOCX','VIDEO','AUDIO','IMAGE','OTHER')", name="ck_resources_kind"))
    op.create_index("ix_resources_owner_id", "resources", ["owner_id"])
    op.create_table("resource_versions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("resource_id", uuid, sa.ForeignKey("resources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False), sa.Column("object_key", sa.String(700), nullable=False, unique=True),
        sa.Column("content_type", sa.String(150), nullable=False), sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("checksum_sha256", sa.String(64)), sa.Column("state", sa.String(24), nullable=False, server_default="UPLOADED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint("resource_id", "version_no"))
    op.create_index("ix_resource_versions_resource_id", "resource_versions", ["resource_id"])
    op.create_foreign_key("fk_resources_current_version", "resources", "resource_versions", ["current_version_id"], ["id"], ondelete="SET NULL")
    op.create_table("course_resources",
        sa.Column("course_id", uuid, sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("resource_id", uuid, sa.ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chapter_id", uuid, sa.ForeignKey("course_chapters.id", ondelete="SET NULL")),
        sa.Column("added_by", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False, server_default=now))
    op.create_table("upload_sessions",
        sa.Column("id", uuid, primary_key=True), sa.Column("user_id", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("course_id", uuid, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_id", uuid, sa.ForeignKey("course_chapters.id", ondelete="SET NULL")),
        sa.Column("idempotency_key", sa.String(100), nullable=False), sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False), sa.Column("content_type", sa.String(150), nullable=False),
        sa.Column("expected_size", sa.BigInteger, nullable=False), sa.Column("object_key", sa.String(700), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("resource_id", uuid, sa.ForeignKey("resources.id")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint("user_id", "idempotency_key"))
    op.create_index("ix_upload_sessions_user_id", "upload_sessions", ["user_id"])
    op.create_table("processing_jobs",
        sa.Column("id", uuid, primary_key=True), sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False, unique=True),
        sa.Column("resource_version_id", uuid, sa.ForeignKey("resource_versions.id", ondelete="CASCADE")),
        sa.Column("state", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("lease_until", sa.DateTime(timezone=True)), sa.Column("worker_id", sa.String(100)),
        sa.Column("cancel_requested", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("error_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("state IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')", name="ck_processing_jobs_state"))
    op.create_index("ix_processing_jobs_claim", "processing_jobs", ["kind", "state", "available_at", "lease_until"])
    op.create_index("ix_processing_jobs_resource", "processing_jobs", ["resource_version_id"])

def downgrade():
    op.drop_table("processing_jobs")
    op.drop_table("upload_sessions")
    op.drop_table("course_resources")
    op.drop_constraint("fk_resources_current_version", "resources", type_="foreignkey")
    op.drop_table("resource_versions")
    op.drop_table("resources")
