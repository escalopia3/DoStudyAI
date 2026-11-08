from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
revision='0007'
down_revision='0006'
branch_labels=depends_on=None
def upgrade():
    op.create_table('learning_memories',sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('user_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('course_id',UUID(as_uuid=True),sa.ForeignKey('courses.id',ondelete='CASCADE')),
        sa.Column('kind',sa.String(30),nullable=False),sa.Column('content',sa.String(500),nullable=False),
        sa.Column('source_run_id',UUID(as_uuid=True),sa.ForeignKey('agent_runs.id')),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_learning_memories_user_id','learning_memories',['user_id'])
    op.create_index('ix_learning_memories_course_id','learning_memories',['course_id'])
    op.create_table('practice_attempts',sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('user_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('course_id',UUID(as_uuid=True),sa.ForeignKey('courses.id',ondelete='CASCADE'),nullable=False),
        sa.Column('question',sa.Text,nullable=False),sa.Column('expected_answer',sa.Text,nullable=False),
        sa.Column('submitted_answer',sa.Text,nullable=False),sa.Column('correct',sa.Boolean,nullable=False),
        sa.Column('source_ids',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_practice_attempts_user_id','practice_attempts',['user_id'])
    op.create_index('ix_practice_attempts_course_id','practice_attempts',['course_id'])
def downgrade():
    op.drop_table('practice_attempts')
    op.drop_table('learning_memories')
