"""Versioned knowledge projection and active index pointers."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = '0005'
down_revision = '0004'
branch_labels = depends_on = None

def upgrade():
    op.create_table('knowledge_indexes',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('resource_id', UUID(as_uuid=True), sa.ForeignKey('resources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('resource_version_id', UUID(as_uuid=True), sa.ForeignKey('resource_versions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_id', UUID(as_uuid=True), sa.ForeignKey('processing_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('collection', sa.String(100), nullable=False),
        sa.Column('config', JSONB, nullable=False), sa.Column('manifest', JSONB, nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index('ix_knowledge_indexes_resource_id', 'knowledge_indexes', ['resource_id'])
    op.create_index('ix_knowledge_indexes_job_id', 'knowledge_indexes', ['job_id'])
    op.create_table('active_knowledge_indexes',
        sa.Column('resource_id', UUID(as_uuid=True), sa.ForeignKey('resources.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('index_id', UUID(as_uuid=True), sa.ForeignKey('knowledge_indexes.id'), nullable=False))

def downgrade():
    op.drop_table('active_knowledge_indexes')
    op.drop_table('knowledge_indexes')
