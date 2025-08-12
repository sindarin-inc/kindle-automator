"""Add booting status fields to vnc_instances table

Revision ID: 013
Revises: 012
Create Date: 2025-08-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Boolean, DateTime

# revision identifiers
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    """Add booting status fields to vnc_instances table."""
    # Check if columns already exist
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col["name"] for col in inspector.get_columns("vnc_instances")]

    if "is_booting" not in columns:
        op.add_column(
            "vnc_instances",
            sa.Column("is_booting", Boolean, nullable=False, server_default="false"),
        )

    if "boot_started_at" not in columns:
        op.add_column(
            "vnc_instances",
            sa.Column("boot_started_at", DateTime, nullable=True),
        )

    # Create index for finding booting instances
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("vnc_instances")]
    if "idx_vnc_instances_booting" not in existing_indexes:
        op.create_index(
            "idx_vnc_instances_booting",
            "vnc_instances",
            ["assigned_profile"],
            postgresql_where=sa.text("is_booting = true"),
        )


def downgrade():
    """Remove booting status fields from vnc_instances table."""
    op.drop_index("idx_vnc_instances_booting", table_name="vnc_instances")
    op.drop_column("vnc_instances", "boot_started_at")
    op.drop_column("vnc_instances", "is_booting")
