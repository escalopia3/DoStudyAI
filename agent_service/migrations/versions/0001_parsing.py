"""Initial durable parsing queue; deliberately no chunk or vector tables."""
from alembic import op
import sqlalchemy as sa

revision = "0001_parsing"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_parse_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("lease_until", sa.Float(precision=53), nullable=False),
        sa.Column("available_at", sa.Float(precision=53), nullable=False),
        sa.Column("artifact_prefix", sa.String(512)), sa.Column("error_code", sa.String(64)))
    op.create_index("ix_parse_claim", "ai_parse_jobs", ["state", "available_at", "lease_until"])
    op.create_table("ai_knowledge_outbox",
        sa.Column("id", sa.String(100), primary_key=True), sa.Column("payload", sa.Text, nullable=False),
        sa.Column("delivered", sa.Integer, nullable=False), sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("available_at", sa.Float(precision=53), nullable=False))
    op.create_index("ix_outbox_due", "ai_knowledge_outbox", ["delivered", "available_at"])


def downgrade():
    op.drop_table("ai_knowledge_outbox")
    op.drop_table("ai_parse_jobs")
