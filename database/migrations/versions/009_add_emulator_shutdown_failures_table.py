"""add emulator shutdown failures table

Revision ID: 009
Revises: 008
Create Date: 2025-08-04 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create emulator_shutdown_failures table
    op.create_table(
        "emulator_shutdown_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_email", sa.String(255), nullable=False),
        sa.Column("failure_type", sa.String(50), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("emulator_id", sa.String(50), nullable=True),
        sa.Column("snapshot_attempted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("placemark_sync_attempted", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes for efficient queries
    op.create_index("idx_emulator_shutdown_failures_user_email", "emulator_shutdown_failures", ["user_email"])
    op.create_index(
        "idx_emulator_shutdown_failures_failure_type", "emulator_shutdown_failures", ["failure_type"]
    )
    op.create_index("idx_emulator_shutdown_failures_created_at", "emulator_shutdown_failures", ["created_at"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_emulator_shutdown_failures_created_at", table_name="emulator_shutdown_failures")
    op.drop_index("idx_emulator_shutdown_failures_failure_type", table_name="emulator_shutdown_failures")
    op.drop_index("idx_emulator_shutdown_failures_user_email", table_name="emulator_shutdown_failures")

    # Drop the table
    op.drop_table("emulator_shutdown_failures")
