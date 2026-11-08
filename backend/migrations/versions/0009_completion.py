from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision='0009'
down_revision='0008'
branch_labels=depends_on=None

def upgrade():
    op.add_column('agent_threads',sa.Column('history_summary',JSONB,nullable=False,server_default='{}'))
    op.add_column('practice_questions',sa.Column('rubric',JSONB,nullable=False,server_default='[]'))
    op.add_column('practice_attempts',sa.Column('feedback',JSONB,nullable=False,server_default='{}'))

def downgrade():
    op.drop_column('practice_attempts','feedback')
    op.drop_column('practice_questions','rubric')
    op.drop_column('agent_threads','history_summary')
