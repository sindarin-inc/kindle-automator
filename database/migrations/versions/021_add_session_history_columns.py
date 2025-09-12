"""Add session history columns to book_sessions table.

Revision ID: 021
Revises: 020
Create Date: 2025-09-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade():
    """Add previous_session_key and previous_position columns to book_sessions table."""
    # Check if columns already exist (for idempotency)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'book_sessions' 
            AND column_name IN ('previous_session_key', 'previous_position')
            """
        )
    )
    existing_columns = {row[0] for row in result}

    # Add previous_session_key column if it doesn't exist
    if "previous_session_key" not in existing_columns:
        op.add_column("book_sessions", sa.Column("previous_session_key", sa.String(255), nullable=True))

    # Add previous_position column if it doesn't exist
    if "previous_position" not in existing_columns:
        op.add_column("book_sessions", sa.Column("previous_position", sa.Integer(), nullable=True))


def downgrade():
    """Remove previous_session_key and previous_position columns from book_sessions table."""
    op.drop_column("book_sessions", "previous_position")
    op.drop_column("book_sessions", "previous_session_key")
