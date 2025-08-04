"""Add snapshot_dirty field to track when snapshots need resaving.

Revision ID: 005
Revises: 004
Create Date: 2025-07-31
"""

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("snapshot_dirty", sa.Boolean(), nullable=False, server_default=sa.sql.false()),
    )
    op.add_column(
        "users",
        sa.Column("snapshot_dirty_since", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("users", "snapshot_dirty_since")
    op.drop_column("users", "snapshot_dirty")
