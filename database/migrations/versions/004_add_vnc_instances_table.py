"""add_vnc_instances_table

Revision ID: 39bc59a24564
Revises: 003
Create Date: 2025-07-25 18:01:10.002430

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create vnc_instances table
    op.create_table(
        "vnc_instances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("display", sa.Integer(), nullable=False),
        sa.Column("vnc_port", sa.Integer(), nullable=False),
        sa.Column("appium_port", sa.Integer(), nullable=False),
        sa.Column("emulator_port", sa.Integer(), nullable=False),
        sa.Column("emulator_id", sa.String(length=50), nullable=True),
        sa.Column("assigned_profile", sa.String(length=255), nullable=True),
        sa.Column("appium_pid", sa.Integer(), nullable=True),
        sa.Column("appium_running", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("appium_last_health_check", sa.DateTime(), nullable=True),
        sa.Column("appium_system_port", sa.Integer(), nullable=False),
        sa.Column("appium_chromedriver_port", sa.Integer(), nullable=False),
        sa.Column("appium_mjpeg_server_port", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vnc_instances_display"), "vnc_instances", ["display"], unique=True)
    op.create_index(op.f("ix_vnc_instances_vnc_port"), "vnc_instances", ["vnc_port"], unique=True)
    op.create_index(op.f("ix_vnc_instances_appium_port"), "vnc_instances", ["appium_port"], unique=True)
    op.create_index(op.f("ix_vnc_instances_emulator_port"), "vnc_instances", ["emulator_port"], unique=True)
    op.create_index("idx_vnc_assigned_profile", "vnc_instances", ["assigned_profile"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_vnc_assigned_profile", table_name="vnc_instances")
    op.drop_index(op.f("ix_vnc_instances_emulator_port"), table_name="vnc_instances")
    op.drop_index(op.f("ix_vnc_instances_appium_port"), table_name="vnc_instances")
    op.drop_index(op.f("ix_vnc_instances_vnc_port"), table_name="vnc_instances")
    op.drop_index(op.f("ix_vnc_instances_display"), table_name="vnc_instances")
    op.drop_table("vnc_instances")
