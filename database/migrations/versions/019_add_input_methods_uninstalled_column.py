"""Add input_methods_uninstalled column to emulator_settings

Revision ID: 019
Revises: 018
Create Date: 2025-08-16 14:00:00

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check if column exists before adding (idempotent)
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='emulator_settings' 
            AND column_name='input_methods_uninstalled'
            """
        )
    )
    if not result.fetchone():
        # Add input_methods_uninstalled column with default false
        op.add_column(
            "emulator_settings",
            sa.Column("input_methods_uninstalled", sa.Boolean(), nullable=False, server_default="false"),
        )
        print("Added input_methods_uninstalled column to emulator_settings")
    else:
        print("input_methods_uninstalled column already exists, skipping")


def downgrade() -> None:
    # Remove input_methods_uninstalled column
    op.drop_column("emulator_settings", "input_methods_uninstalled")
