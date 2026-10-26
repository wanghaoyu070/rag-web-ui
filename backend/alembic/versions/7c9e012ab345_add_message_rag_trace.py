"""Store the actual RAG execution trace on each assistant message."""
from alembic import op
import sqlalchemy as sa
revision = "7c9e012ab345"
down_revision = "3580c0dcd005"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("messages", sa.Column("rag_trace", sa.JSON(), nullable=True))

def downgrade():
    op.drop_column("messages", "rag_trace")
