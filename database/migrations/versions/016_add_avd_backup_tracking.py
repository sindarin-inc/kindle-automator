"""Add AVD backup tracking columns"""

import logging
from datetime import datetime, timezone

from alembic import op
from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, text

logger = logging.getLogger(__name__)

# Metadata instance for table reflection
metadata = MetaData()


def upgrade():
    """Add columns for AVD backup tracking"""
    logger.info("Adding AVD backup tracking columns to users table")

    # Get database connection
    connection = op.get_bind()

    # Check if columns already exist (idempotency)
    result = connection.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
    )
    existing_columns = [row[0] for row in result]

    # Add backup_date column if it doesn't exist
    if "backup_date" not in existing_columns:
        op.add_column("users", Column("backup_date", DateTime, nullable=True))
        logger.info("Added backup_date column to users table")
    else:
        logger.info("backup_date column already exists in users table")

    # Add backup_hostname column if it doesn't exist
    if "backup_hostname" not in existing_columns:
        op.add_column("users", Column("backup_hostname", String(255), nullable=True))
        logger.info("Added backup_hostname column to users table")
    else:
        logger.info("backup_hostname column already exists in users table")

    # Add avd_dirty column if it doesn't exist
    if "avd_dirty" not in existing_columns:
        op.add_column("users", Column("avd_dirty", Boolean, nullable=False, server_default="false"))
        logger.info("Added avd_dirty column to users table")
    else:
        logger.info("avd_dirty column already exists in users table")

    # Add avd_dirty_since column if it doesn't exist
    if "avd_dirty_since" not in existing_columns:
        op.add_column("users", Column("avd_dirty_since", DateTime, nullable=True))
        logger.info("Added avd_dirty_since column to users table")
    else:
        logger.info("avd_dirty_since column already exists in users table")

    logger.info("AVD backup tracking columns migration completed")


def downgrade():
    """Remove AVD backup tracking columns"""
    logger.info("Removing AVD backup tracking columns from users table")

    # Get database connection
    connection = op.get_bind()

    # Check if columns exist before dropping (idempotency)
    result = connection.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")
    )
    existing_columns = [row[0] for row in result]

    if "backup_date" in existing_columns:
        op.drop_column("users", "backup_date")
        logger.info("Dropped backup_date column from users table")

    if "backup_hostname" in existing_columns:
        op.drop_column("users", "backup_hostname")
        logger.info("Dropped backup_hostname column from users table")

    if "avd_dirty" in existing_columns:
        op.drop_column("users", "avd_dirty")
        logger.info("Dropped avd_dirty column from users table")

    if "avd_dirty_since" in existing_columns:
        op.drop_column("users", "avd_dirty_since")
        logger.info("Dropped avd_dirty_since column from users table")

    logger.info("AVD backup tracking columns removal completed")
