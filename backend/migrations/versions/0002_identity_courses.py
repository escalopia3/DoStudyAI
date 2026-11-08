"""Identity, revocable sessions, courses and course-scoped authorization."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    now = sa.text("CURRENT_TIMESTAMP")
    op.create_table("users",
        sa.Column("id", uuid, primary_key=True), sa.Column("username", sa.String(32), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False), sa.Column("nickname", sa.String(50), nullable=False),
        sa.Column("avatar", sa.String(512)), sa.Column("role", sa.String(20), nullable=False, server_default="USER"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("role IN ('USER','ADMIN')", name="ck_users_role"))
    op.create_table("auth_sessions",
        sa.Column("token_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table("login_attempts",
        sa.Column("username", sa.String(32), primary_key=True), sa.Column("failures", sa.Integer, nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("courses",
        sa.Column("id", uuid, primary_key=True), sa.Column("name", sa.String(100), nullable=False),
        sa.Column("semester", sa.String(50), nullable=False, server_default=""),
        sa.Column("description", sa.String(1000), nullable=False, server_default=""),
        sa.Column("created_by", uuid, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now))
    op.create_table("course_members",
        sa.Column("course_id", uuid, sa.ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("role IN ('OWNER','TEACHER','STUDENT')", name="ck_course_members_role"))
    op.create_index("ix_course_members_user", "course_members", ["user_id", "course_id"])
    op.create_table("course_chapters",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("course_id", uuid, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False), sa.Column("sort_order", sa.Integer, nullable=False),
        sa.UniqueConstraint("course_id", "sort_order"))
    op.create_index("ix_course_chapters_course", "course_chapters", ["course_id", "sort_order"])

def downgrade():
    for table in ("course_chapters", "course_members", "courses", "login_attempts", "auth_sessions", "users"):
        op.drop_table(table)
