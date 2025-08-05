"""Fix VNC unique constraints to be per-server instead of global.

Revision ID: 011
Revises: 010
Create Date: 2025-08-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Drop the old global unique constraints on display and ports that were
    created as indexes in migration 004 but not properly dropped in migration 010.

    The old constraints prevent multiple servers from having the same display numbers,
    but we want each server to have independent display numbers (1, 2, 3...).
    """

    # Drop the old single-column unique indexes that were created in migration 004
    # These cause the "duplicate key value violates unique constraint" errors
    try:
        op.drop_index("ix_vnc_instances_display", table_name="vnc_instances")
    except Exception as e:
        print(f"Note: ix_vnc_instances_display might already be dropped: {e}")

    try:
        op.drop_index("ix_vnc_instances_vnc_port", table_name="vnc_instances")
    except Exception as e:
        print(f"Note: ix_vnc_instances_vnc_port might already be dropped: {e}")

    try:
        op.drop_index("ix_vnc_instances_appium_port", table_name="vnc_instances")
    except Exception as e:
        print(f"Note: ix_vnc_instances_appium_port might already be dropped: {e}")

    try:
        op.drop_index("ix_vnc_instances_emulator_port", table_name="vnc_instances")
    except Exception as e:
        print(f"Note: ix_vnc_instances_emulator_port might already be dropped: {e}")

    # The composite constraints (server_name, display) etc. should already exist
    # from migration 010, so we don't need to recreate them


def downgrade() -> None:
    """
    Recreate the global unique constraints (not recommended as it breaks multi-server setup).
    """
    op.create_index("ix_vnc_instances_display", "vnc_instances", ["display"], unique=True)
    op.create_index("ix_vnc_instances_vnc_port", "vnc_instances", ["vnc_port"], unique=True)
    op.create_index("ix_vnc_instances_appium_port", "vnc_instances", ["appium_port"], unique=True)
    op.create_index("ix_vnc_instances_emulator_port", "vnc_instances", ["emulator_port"], unique=True)
