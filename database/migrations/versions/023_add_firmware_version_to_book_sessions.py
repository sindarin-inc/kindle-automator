"""Add firmware version to book sessions

Revision ID: 023
Revises: 022
Create Date: 2025-01-12
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "023"
down_revision = "022"
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
            AND column_name='firmware_version'
            """
        )
    )
    if not result.fetchone():
        op.add_column(
            "book_sessions",
            sa.Column("firmware_version", sa.String(50), nullable=True),
        )
        print("Added firmware_version column to book_sessions table")
    else:
        print("firmware_version column already exists in book_sessions table")


def downgrade():
    op.drop_column("book_sessions", "firmware_version")
