"""Convert all DateTime columns to timezone-aware

Revision ID: 027
Revises: 026
Create Date: 2024-09-24 09:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert all DateTime columns to timezone-aware (TIMESTAMP WITH TIME ZONE)"""

    # List of tables and columns to convert
    # Format: (table_name, column_name)
    columns_to_migrate = [
        # Users table
        ("users", "last_used"),
        ("users", "auth_date"),
        ("users", "auth_failed_date"),
        ("users", "last_snapshot_timestamp"),
        ("users", "snapshot_dirty_since"),
        ("users", "cold_storage_date"),
        ("users", "created_at"),
        ("users", "updated_at"),
        # Emulator settings
        ("emulator_settings", "memory_optimization_timestamp"),
        # Library settings
        ("library_settings", "last_series_group_check"),
        # VNC instances
        ("vnc_instances", "appium_last_health_check"),
        ("vnc_instances", "boot_started_at"),
        ("vnc_instances", "created_at"),
        ("vnc_instances", "updated_at"),
        # Staff tokens
        ("staff_tokens", "created_at"),
        ("staff_tokens", "last_used"),
        ("staff_tokens", "revoked_at"),
        # Emulator shutdown failures
        ("emulator_shutdown_failures", "created_at"),
        # Book positions
        ("book_positions", "created_at"),
        # Auth token history
        ("auth_token_history", "event_date"),
        ("auth_token_history", "created_at"),
        # Book sessions
        ("book_sessions", "created_at"),
        # Reading sessions - may already be timezone-aware
        ("reading_sessions", "started_at"),
        ("reading_sessions", "ended_at"),
        ("reading_sessions", "last_activity_at"),
    ]

    # Get the connection to check current state
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table_name, column_name in columns_to_migrate:
        # Check if table exists
        if not inspector.has_table(table_name):
            continue

        # Get current column info
        columns = inspector.get_columns(table_name)
        column_info = next((col for col in columns if col["name"] == column_name), None)

        if not column_info:
            continue

        # Check if already timezone-aware
        if hasattr(column_info["type"], "timezone") and column_info["type"].timezone:
            continue

        # Convert to timezone-aware, interpreting existing values as UTC
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN {column_name}
            TYPE TIMESTAMP WITH TIME ZONE
            USING {column_name} AT TIME ZONE 'UTC'
        """
        )


def downgrade() -> None:
    """Convert back to timezone-naive DateTime"""

    # Same list of columns
    columns_to_migrate = [
        ("users", "last_used"),
        ("users", "auth_date"),
        ("users", "auth_failed_date"),
        ("users", "last_snapshot_timestamp"),
        ("users", "snapshot_dirty_since"),
        ("users", "cold_storage_date"),
        ("users", "created_at"),
        ("users", "updated_at"),
        ("emulator_settings", "memory_optimization_timestamp"),
        ("library_settings", "last_series_group_check"),
        ("vnc_instances", "appium_last_health_check"),
        ("vnc_instances", "boot_started_at"),
        ("vnc_instances", "created_at"),
        ("vnc_instances", "updated_at"),
        ("staff_tokens", "created_at"),
        ("staff_tokens", "last_used"),
        ("staff_tokens", "revoked_at"),
        ("emulator_shutdown_failures", "created_at"),
        ("book_positions", "created_at"),
        ("auth_token_history", "event_date"),
        ("auth_token_history", "created_at"),
        ("book_sessions", "created_at"),
        ("reading_sessions", "started_at"),
        ("reading_sessions", "ended_at"),
        ("reading_sessions", "last_activity_at"),
    ]

    # Get the connection to check current state
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table_name, column_name in columns_to_migrate:
        # Check if table exists
        if not inspector.has_table(table_name):
            continue

        # Get current column info
        columns = inspector.get_columns(table_name)
        column_info = next((col for col in columns if col["name"] == column_name), None)

        if not column_info:
            continue

        # Check if already timezone-naive
        if not (hasattr(column_info["type"], "timezone") and column_info["type"].timezone):
            continue

        # Convert back to timezone-naive, keeping UTC values
        op.execute(
            f"""
            ALTER TABLE {table_name}
            ALTER COLUMN {column_name}
            TYPE TIMESTAMP WITHOUT TIME ZONE
            USING {column_name} AT TIME ZONE 'UTC'
        """
        )
