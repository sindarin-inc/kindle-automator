"""Add user agent to book sessions

Revision ID: 024
Revises: 023
Create Date: 2025-01-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    # Check if column already exists (for idempotency)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='book_sessions' 
            AND column_name='user_agent'
            """
        )
    )
    if not result.fetchone():
        op.add_column(
            "book_sessions",
            sa.Column("user_agent", sa.Text, nullable=True),
        )
        print("Added user_agent column to book_sessions table")
    else:
        print("user_agent column already exists in book_sessions table")


def downgrade():
    op.drop_column("book_sessions", "user_agent")
