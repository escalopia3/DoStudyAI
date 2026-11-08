"""Bounded agent recovery and durable request correlation."""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = depends_on = None


def upgrade():
    for column in (
        sa.Column('claim_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_claim_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('deadline_at', sa.DateTime(timezone=True)),
        sa.Column('request_id', sa.String(36)),
    ):
        op.add_column('agent_runs', column)
    op.create_index('ix_agent_runs_state_created', 'agent_runs', ['state', 'created_at'])


def downgrade():
    op.drop_index('ix_agent_runs_state_created', table_name='agent_runs')
    for name in ('request_id', 'deadline_at', 'started_at', 'max_claim_attempts', 'claim_attempts'):
        op.drop_column('agent_runs', name)
