"""add staff tokens table

Revision ID: 008
Revises: 007
Create Date: 2025-08-01 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create staff_tokens table
    op.create_table(
        "staff_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used", sa.DateTime(), nullable=True),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_staff_tokens_token"),
    )

    # Create index on token for fast lookups
    op.create_index("idx_staff_tokens_token", "staff_tokens", ["token"])

    # Create index on revoked for filtering active tokens
    op.create_index("idx_staff_tokens_revoked", "staff_tokens", ["revoked"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_staff_tokens_revoked", table_name="staff_tokens")
    op.drop_index("idx_staff_tokens_token", table_name="staff_tokens")

    # Drop the table
    op.drop_table("staff_tokens")
