"""Initial migration - Create users and related tables

Revision ID: 001
Revises: 
Create Date: 2025-07-17

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("avd_name", sa.String(length=255), nullable=True),
        sa.Column("last_used", sa.DateTime(), nullable=True),
        sa.Column("auth_date", sa.DateTime(), nullable=True),
        sa.Column("was_running_at_restart", sa.Boolean(), nullable=True),
        sa.Column("styles_updated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("timezone", sa.String(length=50), nullable=True),
        sa.Column("created_from_seed_clone", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("post_boot_randomized", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("needs_device_randomization", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_snapshot_timestamp", sa.DateTime(), nullable=True),
        sa.Column("last_snapshot", sa.String(length=255), nullable=True),
        sa.Column("kindle_version_name", sa.String(length=50), nullable=True),
        sa.Column("kindle_version_code", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(
        op.f("ix_users_last_used"),
        "users",
        ["last_used"],
        unique=False,
    )

    # Create emulator_settings table
    op.create_table(
        "emulator_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hw_overlays_disabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("animations_disabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sleep_disabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("status_bar_disabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_updates_disabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("memory_optimizations_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("memory_optimization_timestamp", sa.DateTime(), nullable=True),
        sa.Column("appium_device_initialized", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create device_identifiers table
    op.create_table(
        "device_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("hw_wifi_mac", sa.String(length=20), nullable=True),
        sa.Column("hw_ethernet_mac", sa.String(length=20), nullable=True),
        sa.Column("ro_serialno", sa.String(length=50), nullable=True),
        sa.Column("ro_build_id", sa.String(length=50), nullable=True),
        sa.Column("ro_product_name", sa.String(length=100), nullable=True),
        sa.Column("android_id", sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create library_settings table
    op.create_table(
        "library_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("view_type", sa.String(length=20), nullable=True),
        sa.Column("group_by_series", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("actively_reading_title", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create reading_settings table
    op.create_table(
        "reading_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("theme", sa.String(length=20), nullable=True),
        sa.Column("font_size", sa.String(length=20), nullable=True),
        sa.Column("real_time_highlighting", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("about_book", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("page_turn_animation", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("popular_highlights", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("highlight_menu", sa.Boolean(), nullable=False, server_default="false"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create user_preferences table
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("preference_key", sa.String(length=255), nullable=False),
        sa.Column("preference_value", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "preference_key", name="uq_user_preference"),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
    op.drop_table("reading_settings")
    op.drop_table("library_settings")
    op.drop_table("device_identifiers")
    op.drop_table("emulator_settings")
    op.drop_index(op.f("ix_users_last_used"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
