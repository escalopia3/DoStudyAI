from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "legacy_study_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_legacy_study_records_course_id", "legacy_study_records", ["course_id"])

def downgrade():
    op.drop_table("legacy_study_records")
