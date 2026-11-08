from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0008'
down_revision = '0007'
branch_labels = depends_on = None

def upgrade():
    op.add_column('learning_memories', sa.Column('status', sa.String(12), nullable=False, server_default='confirmed'))
    op.create_table('practice_questions',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey('agent_runs.id'), nullable=False),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('expected_answer', sa.Text, nullable=False),
        sa.Column('evidence', JSONB, nullable=False))
    op.create_index('ix_practice_questions_run_id','practice_questions',['run_id'])
    op.add_column('practice_attempts', sa.Column('question_id', UUID(as_uuid=True), sa.ForeignKey('practice_questions.id')))

def downgrade():
    op.drop_column('practice_attempts','question_id')
    op.drop_table('practice_questions')
    op.drop_column('learning_memories','status')
