from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID,JSONB
revision='0006'
down_revision='0005'
branch_labels=depends_on=None
def upgrade():
    op.create_table('agent_threads',sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('user_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('course_id',UUID(as_uuid=True),sa.ForeignKey('courses.id'),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_agent_threads_user_id','agent_threads',['user_id'])
    op.create_index('ix_agent_threads_course_id','agent_threads',['course_id'])
    op.create_table('agent_runs',sa.Column('id',UUID(as_uuid=True),primary_key=True),
        sa.Column('thread_id',UUID(as_uuid=True),sa.ForeignKey('agent_threads.id'),nullable=False),
        sa.Column('state',sa.String(20),nullable=False),sa.Column('input_text',sa.Text,nullable=False),sa.Column('model_id',sa.String(100)),
        sa.Column('checkpoint',JSONB,nullable=False),sa.Column('answer',sa.Text,nullable=False),
        sa.Column('usage',JSONB,nullable=False),sa.Column('lease_token',sa.String(36)),
        sa.Column('lease_until',sa.DateTime(timezone=True)),sa.Column('cancel_requested',sa.Boolean,nullable=False),
        sa.Column('error_code',sa.String(80)),sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_agent_runs_thread_id','agent_runs',['thread_id'])
    op.execute("CREATE UNIQUE INDEX uq_agent_one_active ON agent_runs (thread_id) WHERE state IN ('QUEUED','RUNNING')")
    op.create_table('agent_events',sa.Column('id',sa.BigInteger,primary_key=True,autoincrement=True),
        sa.Column('run_id',UUID(as_uuid=True),sa.ForeignKey('agent_runs.id'),nullable=False),
        sa.Column('kind',sa.String(40),nullable=False),sa.Column('data',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
    op.create_index('ix_agent_events_run_id','agent_events',['run_id'])
    op.create_table('learning_preferences',sa.Column('user_id',UUID(as_uuid=True),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('key',sa.String(50),primary_key=True),sa.Column('value',sa.String(300),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False))
def downgrade():
    op.drop_table('learning_preferences');op.drop_table('agent_events');op.drop_table('agent_runs');op.drop_table('agent_threads')
