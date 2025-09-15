"""Add reading_sessions table for tracking complete reading sessions

Revision ID: 025
Revises: 024
Create Date: 2025-09-15
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    """Add the reading_sessions table for tracking reading sessions."""
    # Check if table already exists (for idempotency)
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'reading_sessions')")
    )
    table_exists = result.scalar()

    if table_exists:
        print("Table 'reading_sessions' already exists, skipping creation")
        return

    print("Creating 'reading_sessions' table...")

    # Create the table
    conn.execute(
        sa.text(
            """
        CREATE TABLE reading_sessions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            book_title TEXT NOT NULL,
            session_key VARCHAR(255),

            -- Position tracking
            start_position INTEGER NOT NULL DEFAULT 0,
            current_position INTEGER NOT NULL DEFAULT 0,
            max_position INTEGER NOT NULL DEFAULT 0,

            -- Navigation stats
            total_pages_forward INTEGER NOT NULL DEFAULT 0,
            total_pages_backward INTEGER NOT NULL DEFAULT 0,
            navigation_count INTEGER NOT NULL DEFAULT 0,

            -- Session metadata
            firmware_version VARCHAR(50),
            user_agent TEXT,

            -- Timestamps
            started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            last_activity_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            ended_at TIMESTAMP WITH TIME ZONE,

            -- Session state
            is_active BOOLEAN NOT NULL DEFAULT TRUE
        )
    """
        )
    )

    # Create indexes
    conn.execute(
        sa.text("CREATE INDEX idx_reading_session_user_book ON reading_sessions(user_id, book_title)")
    )
    conn.execute(sa.text("CREATE INDEX idx_reading_session_active ON reading_sessions(is_active)"))
    conn.execute(sa.text("CREATE INDEX idx_reading_session_session_key ON reading_sessions(session_key)"))
    conn.execute(sa.text("CREATE INDEX idx_reading_session_started_at ON reading_sessions(started_at)"))
    conn.execute(
        sa.text("CREATE INDEX idx_reading_session_last_activity ON reading_sessions(last_activity_at)")
    )

    print("Successfully created 'reading_sessions' table with indexes")


def downgrade():
    """Remove the reading_sessions table."""
    print("Dropping 'reading_sessions' table...")
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS reading_sessions CASCADE"))
    print("Successfully dropped 'reading_sessions' table")
