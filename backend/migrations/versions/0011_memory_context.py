"""Versioned automatic learning memory and chronological history lookup."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0011'
down_revision='0010'
branch_labels=depends_on=None

def upgrade():
    op.add_column('learning_memories',sa.Column('fact_key',sa.String(100),nullable=True))
    op.add_column('learning_memories',sa.Column('revision',sa.Integer(),nullable=False,server_default='1'))
    op.add_column('learning_memories',sa.Column('origin',JSONB,nullable=False,server_default='{}'))
    op.add_column('learning_memories',sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()))
    op.create_index('ix_learning_memories_fact_key','learning_memories',['fact_key'])
    op.create_index('ix_memory_active_scope','learning_memories',['user_id','course_id','status'])
    op.create_index('uq_memory_active_fact','learning_memories',[
        'user_id',sa.text("COALESCE(course_id, '00000000-0000-0000-0000-000000000000'::uuid)"),'fact_key'],
        unique=True,postgresql_where=sa.text("status = 'confirmed' AND fact_key IS NOT NULL"))
    op.create_index('ix_agent_runs_thread_order','agent_runs',['thread_id','created_at','id'])

def downgrade():
    for name,table in [('ix_agent_runs_thread_order','agent_runs'),('uq_memory_active_fact','learning_memories'),
        ('ix_memory_active_scope','learning_memories'),('ix_learning_memories_fact_key','learning_memories')]:op.drop_index(name,table_name=table)
    for name in ('updated_at','origin','revision','fact_key'):op.drop_column('learning_memories',name)
