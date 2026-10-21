"""Immutable knowledge index manifests and the active publication pointer."""
from alembic import op
import sqlalchemy as sa

revision = "0002_knowledge_indexes"
down_revision = "0001_parsing"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("ai_knowledge_indexes",
        sa.Column("index_revision", sa.String(64), primary_key=True),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("source_revision", sa.String(100), nullable=False),
        sa.Column("embedding_version", sa.String(255), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("manifest_json", sa.Text),
        sa.Column("created_at", sa.Float(precision=53), nullable=False),
        sa.Column("published_at", sa.Float(precision=53)))
    op.create_index("ix_knowledge_resource_state", "ai_knowledge_indexes",
                    ["resource_id", "state", "created_at"])
    op.create_table("ai_active_knowledge_indexes",
        sa.Column("resource_id", sa.String(64), primary_key=True),
        sa.Column("source_revision", sa.String(100), nullable=False),
        sa.Column("index_revision", sa.String(64), nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("updated_at", sa.Float(precision=53), nullable=False))


def downgrade():
    op.drop_table("ai_active_knowledge_indexes")
    op.drop_table("ai_knowledge_indexes")

