"""Persist immutable document preview snapshots and processing identity."""
from alembic import op
import sqlalchemy as sa
revision = "83aa022bc456"
down_revision = "7c9e012ab345"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("documents", sa.Column("preview_id", sa.String(36), nullable=True))
    op.add_column("documents", sa.Column("chunk_config", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("chunk_count", sa.Integer(), nullable=True))
    op.add_column("document_uploads", sa.Column("current_preview_id", sa.String(36), nullable=True))
    op.add_column("processing_tasks", sa.Column("preview_id", sa.String(36), nullable=True))
    op.create_unique_constraint("uq_processing_preview", "processing_tasks", ["preview_id"])
    op.add_column("document_chunks", sa.Column("chunk_index", sa.Integer(), nullable=True))
    op.create_table("document_previews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("document_uploads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("snapshot_path", sa.String(255), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("processor_version", sa.String(100), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False))
    op.create_index("ix_document_previews_upload_id", "document_previews", ["upload_id"])
    op.create_index("ix_document_previews_expires_at", "document_previews", ["expires_at"])

def downgrade():
    op.drop_table("document_previews")
    op.drop_column("document_chunks", "chunk_index")
    op.drop_constraint("uq_processing_preview", "processing_tasks", type_="unique")
    op.drop_column("processing_tasks", "preview_id")
    op.drop_column("document_uploads", "current_preview_id")
    for name in ["chunk_count", "chunk_config", "preview_id"]:
        op.drop_column("documents", name)
