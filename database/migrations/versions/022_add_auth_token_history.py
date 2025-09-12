"""Add auth_token_history table for tracking auth gains and losses.

Revision ID: 022
Revises: 021
Create Date: 2025-09-12
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade():
    """Create auth_token_history table and bootstrap with existing data."""
    # Create the auth_token_history table
    op.create_table(
        "auth_token_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),  # 'gained' or 'lost'
        sa.Column("event_date", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    # Create indexes
    op.create_index("idx_auth_history_user_id", "auth_token_history", ["user_id"])
    op.create_index("idx_auth_history_event_date", "auth_token_history", ["event_date"])
    op.create_index("idx_auth_history_event_type", "auth_token_history", ["event_type"])

    # Bootstrap with existing data from users table
    conn = op.get_bind()

    # Insert auth gained events for users with auth_date
    conn.execute(
        text(
            """
            INSERT INTO auth_token_history (user_id, event_type, event_date, created_at)
            SELECT id, 'gained', auth_date, NOW()
            FROM users
            WHERE auth_date IS NOT NULL
        """
        )
    )

    # Insert auth lost events for users with auth_failed_date
    conn.execute(
        text(
            """
            INSERT INTO auth_token_history (user_id, event_type, event_date, created_at)
            SELECT id, 'lost', auth_failed_date, NOW()
            FROM users
            WHERE auth_failed_date IS NOT NULL
        """
        )
    )

    # For demo purposes, add some fake historical data for demo users
    # This helps visualize auth patterns on the dashboard
    conn.execute(
        text(
            """
            INSERT INTO auth_token_history (user_id, event_type, event_date, created_at)
            SELECT 
                u.id,
                'gained',
                u.created_at,
                NOW()
            FROM users u
            WHERE u.email LIKE 'demo%@solreader.com'
            AND NOT EXISTS (
                SELECT 1 FROM auth_token_history 
                WHERE user_id = u.id AND event_type = 'gained'
            )
        """
        )
    )


def downgrade():
    """Drop auth_token_history table."""
    op.drop_table("auth_token_history")
