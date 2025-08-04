"""add vnc_instance user foreign key

Revision ID: 007
Revises: 006
Create Date: 2025-08-01 11:58:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add foreign key constraint from vnc_instances.assigned_profile to users.email
    op.create_foreign_key(
        "fk_vnc_instances_assigned_profile_users_email",
        "vnc_instances",
        "users",
        ["assigned_profile"],
        ["email"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Remove the foreign key constraint
    op.drop_constraint("fk_vnc_instances_assigned_profile_users_email", "vnc_instances", type_="foreignkey")
