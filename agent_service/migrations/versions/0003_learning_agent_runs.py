"""Durable bounded learning-agent runs and callback outbox."""
from alembic import op
import sqlalchemy as sa

revision = "0003_learning_agent_runs"
down_revision = "0002_knowledge_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_agent_runs",
        sa.Column("run_id",sa.String(64),primary_key=True),sa.Column("fingerprint",sa.String(64),nullable=False),
        sa.Column("payload_json",sa.Text,nullable=False),sa.Column("state",sa.String(24),nullable=False),
        sa.Column("attempt",sa.Integer,nullable=False),sa.Column("sequence",sa.Integer,nullable=False),
        sa.Column("lease_until",sa.Float(precision=53),nullable=False),sa.Column("available_at",sa.Float(precision=53),nullable=False),
        sa.Column("deadline_at",sa.Float(precision=53),nullable=False),sa.Column("checkpoint_json",sa.Text),
        sa.Column("result_json",sa.Text),sa.Column("error_code",sa.String(64)),
        sa.Column("created_at",sa.Float(precision=53),nullable=False),sa.Column("updated_at",sa.Float(precision=53),nullable=False))
    op.create_index("ix_agent_claim","ai_agent_runs",["state","available_at","lease_until"])
    op.create_table("ai_agent_outbox",
        sa.Column("event_id",sa.String(100),primary_key=True),sa.Column("run_id",sa.String(64),nullable=False),
        sa.Column("sequence",sa.Integer,nullable=False),sa.Column("payload_json",sa.Text,nullable=False),
        sa.Column("delivered",sa.Integer,nullable=False),sa.Column("attempts",sa.Integer,nullable=False),
        sa.Column("available_at",sa.Float(precision=53),nullable=False))
    op.create_index("ix_agent_outbox_due","ai_agent_outbox",["delivered","available_at"])


def downgrade():
    op.drop_table("ai_agent_outbox")
    op.drop_table("ai_agent_runs")
