"""Fix boot_started_at for existing VNC sessions.

This migration sets boot_started_at for all existing assigned VNC instances
that don't have it set. This allows session duration to be calculated properly.
"""

import logging
from datetime import datetime, timezone

from alembic import op
from sqlalchemy import text

logger = logging.getLogger(__name__)

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    """Set boot_started_at for existing sessions without it."""
    conn = op.get_bind()

    # First check if the column exists (it should from migration 013)
    check_column = text(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='vnc_instances' 
        AND column_name='boot_started_at'
    """
    )
    result = conn.execute(check_column).fetchone()

    if not result:
        logger.warning("boot_started_at column doesn't exist, skipping migration")
        return

    # Update all assigned instances without boot_started_at
    # Use created_at as a reasonable default
    update_query = text(
        """
        UPDATE vnc_instances 
        SET boot_started_at = COALESCE(created_at, NOW())
        WHERE assigned_profile IS NOT NULL 
        AND boot_started_at IS NULL
    """
    )

    result = conn.execute(update_query)
    logger.info(f"Updated boot_started_at for {result.rowcount} VNC instances")


def downgrade():
    """Clear boot_started_at for instances that had it set by this migration."""
    # We can't really tell which ones were set by this migration vs legitimately,
    # so we'll just leave them as-is
    pass
