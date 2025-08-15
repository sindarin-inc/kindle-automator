"""Add cold_storage_date to users table

Revision ID: 015
Revises: 014
Create Date: 2025-08-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import DateTime

# revision identifiers
revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    """Add cold_storage_date column to users table."""
    # Check if column already exists (idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("users")]

    if "cold_storage_date" not in columns:
        op.add_column(
            "users",
            sa.Column("cold_storage_date", DateTime, nullable=True),
        )


def downgrade():
    """Remove cold_storage_date column from users table."""
    # Check if column exists before dropping (idempotent migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("users")]

    if "cold_storage_date" in columns:
        op.drop_column("users", "cold_storage_date")
