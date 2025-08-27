"""Add book_positions table for tracking navigation positions

Revision ID: 016
Revises: 015
Create Date: 2025-08-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text

# revision identifiers
revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    """Create book_positions table."""
    # Check if table already exists (idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "book_positions" not in tables:
        op.create_table(
            "book_positions",
            sa.Column("id", Integer, primary_key=True),
            sa.Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("book_title", Text, nullable=False),
            sa.Column("current_position", Integer, default=0, nullable=False),
            sa.Column("position_updated_at", DateTime, nullable=False),
            sa.Column("created_at", DateTime, nullable=False),
        )

        # Create unique constraint
        op.create_unique_constraint("uq_user_book_position", "book_positions", ["user_id", "book_title"])

        # Create indexes
        op.create_index("idx_book_position_user_id", "book_positions", ["user_id"])
        op.create_index("idx_book_position_updated", "book_positions", ["position_updated_at"])


def downgrade():
    """Drop book_positions table."""
    # Check if table exists before dropping (idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if "book_positions" in tables:
        op.drop_table("book_positions")
