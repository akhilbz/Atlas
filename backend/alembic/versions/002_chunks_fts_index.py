"""Add GIN index on chunks.content for full-text search

Revision ID: 002
Revises: 001
Create Date: 2026-06-16
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_chunks_content_fts ON chunks USING gin(to_tsvector('english', content))"
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_content_fts", table_name="chunks")
