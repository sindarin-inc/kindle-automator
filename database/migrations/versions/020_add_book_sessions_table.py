"""Add book_sessions table for tracking client session keys and navigation offsets.

Revision ID: 020
Revises: 019
Create Date: 2025-09-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    """Create book_sessions table."""
    op.create_table(
        "book_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("book_title", sa.Text(), nullable=False),
        sa.Column("session_key", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "book_title", name="uq_user_book_session"),
    )

    # Create indexes
    op.create_index("idx_book_session_user_id", "book_sessions", ["user_id"])
    op.create_index("idx_book_session_key", "book_sessions", ["session_key"])
    op.create_index("idx_book_session_accessed", "book_sessions", ["last_accessed"])


def downgrade():
    """Drop book_sessions table."""
    op.drop_table("book_sessions")
