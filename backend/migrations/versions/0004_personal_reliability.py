"""Personal ownership and fenced jobs; retain old memberships as an archive."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column('courses', 'created_by', new_column_name='owner_id')
    op.rename_table('course_members', 'legacy_course_members')
    op.add_column('processing_jobs', sa.Column('lease_token', sa.String(36)))
    op.add_column('resource_versions', sa.Column('object_version_id', sa.String(200)))
    op.add_column('upload_sessions', sa.Column('object_version_id', sa.String(200)))
    op.add_column('upload_sessions', sa.Column('expected_sha256', sa.String(64)))

def downgrade():
    for table, col in [('upload_sessions','expected_sha256'), ('upload_sessions','object_version_id'),
                       ('resource_versions','object_version_id'), ('processing_jobs','lease_token')]:
        op.drop_column(table, col)
    op.rename_table('legacy_course_members', 'course_members')
    op.alter_column('courses', 'owner_id', new_column_name='created_by')
