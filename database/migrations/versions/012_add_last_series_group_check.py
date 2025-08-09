"""Add last_series_group_check to library_settings

Revision ID: 012
Revises: 011
Create Date: 2025-08-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import DateTime

# revision identifiers
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    """Add last_series_group_check column to library_settings table."""
    # Check if column already exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("library_settings")]

    if "last_series_group_check" not in columns:
        op.add_column(
            "library_settings",
            sa.Column("last_series_group_check", DateTime, nullable=True),
        )


def downgrade():
    """Remove last_series_group_check column from library_settings table."""
    op.drop_column("library_settings", "last_series_group_check")
