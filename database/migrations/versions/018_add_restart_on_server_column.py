"""Add restart_on_server column to users table for server affinity during restarts.

Revision ID: 018
Revises: 017
Create Date: 2025-01-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text


def upgrade():
    """Add restart_on_server column to track which server should restart a user."""
    # First check if column already exists (for idempotency)
    conn = op.get_bind()
    result = conn.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='users' AND column_name='restart_on_server'"
        )
    )
    if result.fetchone() is None:
        op.add_column("users", sa.Column("restart_on_server", sa.String(255), nullable=True))
        print("Added restart_on_server column to users table")
    else:
        print("restart_on_server column already exists in users table, skipping")


def downgrade():
    """Remove restart_on_server column."""
    op.drop_column("users", "restart_on_server")
