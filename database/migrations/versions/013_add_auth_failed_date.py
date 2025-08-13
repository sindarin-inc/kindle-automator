"""Add auth_failed_date to users table

Revision ID: 013
Revises: 012
Create Date: 2025-08-13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import DateTime

# revision identifiers
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    """Add auth_failed_date column to users table."""
    # Check if column already exists (idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("users")]

    if "auth_failed_date" not in columns:
        op.add_column(
            "users",
            sa.Column("auth_failed_date", DateTime, nullable=True),
        )


def downgrade():
    """Remove auth_failed_date column from users table."""
    op.drop_column("users", "auth_failed_date")
