"""Infrastructure marker only; domain tables are added in later blocks."""
from alembic import op
import sqlalchemy as sa
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("schema_baseline", sa.Column("id", sa.Integer(), primary_key=True))
    op.execute("INSERT INTO schema_baseline (id) VALUES (1)")

def downgrade():
    op.drop_table("schema_baseline")
