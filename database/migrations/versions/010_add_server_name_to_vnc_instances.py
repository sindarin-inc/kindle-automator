"""add server_name to vnc_instances table

Revision ID: 010
Revises: 009
Create Date: 2025-08-05 12:00:00.000000

"""

import socket

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add server_name column to vnc_instances table
    op.add_column("vnc_instances", sa.Column("server_name", sa.String(255), nullable=True))

    # Get the current server hostname
    hostname = socket.gethostname()

    # Update existing rows with the current server's hostname
    op.execute(f"UPDATE vnc_instances SET server_name = '{hostname}' WHERE server_name IS NULL")

    # Make the column not nullable after populating existing rows
    op.alter_column("vnc_instances", "server_name", nullable=False)

    # Drop the existing unique constraints on ports (if they exist)
    # Note: These constraints may not exist in all databases, so we'll check first
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_constraints = [c["name"] for c in inspector.get_unique_constraints("vnc_instances")]

    # Only drop constraints that actually exist
    if "vnc_instances_display_key" in existing_constraints:
        op.drop_constraint("vnc_instances_display_key", "vnc_instances", type_="unique")
    if "vnc_instances_vnc_port_key" in existing_constraints:
        op.drop_constraint("vnc_instances_vnc_port_key", "vnc_instances", type_="unique")
    if "vnc_instances_appium_port_key" in existing_constraints:
        op.drop_constraint("vnc_instances_appium_port_key", "vnc_instances", type_="unique")
    if "vnc_instances_emulator_port_key" in existing_constraints:
        op.drop_constraint("vnc_instances_emulator_port_key", "vnc_instances", type_="unique")

    # Create new unique constraints that include server_name
    op.create_unique_constraint("uq_vnc_server_display", "vnc_instances", ["server_name", "display"])
    op.create_unique_constraint("uq_vnc_server_vnc_port", "vnc_instances", ["server_name", "vnc_port"])
    op.create_unique_constraint("uq_vnc_server_appium_port", "vnc_instances", ["server_name", "appium_port"])
    op.create_unique_constraint(
        "uq_vnc_server_emulator_port", "vnc_instances", ["server_name", "emulator_port"]
    )
    op.create_unique_constraint(
        "uq_vnc_server_appium_system_port", "vnc_instances", ["server_name", "appium_system_port"]
    )
    op.create_unique_constraint(
        "uq_vnc_server_appium_chromedriver_port", "vnc_instances", ["server_name", "appium_chromedriver_port"]
    )
    op.create_unique_constraint(
        "uq_vnc_server_appium_mjpeg_server_port", "vnc_instances", ["server_name", "appium_mjpeg_server_port"]
    )

    # Create index for server_name for faster queries
    op.create_index("idx_vnc_server_name", "vnc_instances", ["server_name"])


def downgrade() -> None:
    # Drop the new unique constraints
    op.drop_constraint("uq_vnc_server_display", "vnc_instances", type_="unique")
    op.drop_constraint("uq_vnc_server_vnc_port", "vnc_instances", type_="unique")
    op.drop_constraint("uq_vnc_server_appium_port", "vnc_instances", type_="unique")
    op.drop_constraint("uq_vnc_server_emulator_port", "vnc_instances", type_="unique")
    op.drop_constraint("uq_vnc_server_appium_system_port", "vnc_instances", type_="unique")
    op.drop_constraint("uq_vnc_server_appium_chromedriver_port", "vnc_instances", type_="unique")
    op.drop_constraint("uq_vnc_server_appium_mjpeg_server_port", "vnc_instances", type_="unique")

    # Drop the index
    op.drop_index("idx_vnc_server_name", table_name="vnc_instances")

    # Recreate the original unique constraints
    op.create_unique_constraint("vnc_instances_display_key", "vnc_instances", ["display"])
    op.create_unique_constraint("vnc_instances_vnc_port_key", "vnc_instances", ["vnc_port"])
    op.create_unique_constraint("vnc_instances_appium_port_key", "vnc_instances", ["appium_port"])
    op.create_unique_constraint("vnc_instances_emulator_port_key", "vnc_instances", ["emulator_port"])

    # Drop the server_name column
    op.drop_column("vnc_instances", "server_name")
