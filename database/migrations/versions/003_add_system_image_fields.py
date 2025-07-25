"""Add system image fields to users table

Revision ID: 003
Revises: 002
Create Date: 2025-07-25

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add android_version column (e.g., "30", "36")
    op.add_column(
        "users",
        sa.Column("android_version", sa.String(10), nullable=True),
    )

    # Add system_image column (e.g., "system-images;android-30;google_apis;x86_64")
    op.add_column(
        "users",
        sa.Column("system_image", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    # Remove system_image column
    op.drop_column("users", "system_image")

    # Remove android_version column
    op.drop_column("users", "android_version")
