"""Migration 025: Add reading_sessions table for tracking complete reading sessions."""

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def upgrade(connection):
    """Add the reading_sessions table for tracking reading sessions."""
    # Check if table already exists
    result = connection.execute(
        text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'reading_sessions')"
        )
    )
    table_exists = result.scalar()

    if table_exists:
        logger.info("Table 'reading_sessions' already exists, skipping creation")
        return

    logger.info("Creating 'reading_sessions' table...")

    # Create the table
    connection.execute(
        text(
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
    connection.execute(
        text("CREATE INDEX idx_reading_session_user_book ON reading_sessions(user_id, book_title)")
    )
    connection.execute(text("CREATE INDEX idx_reading_session_active ON reading_sessions(is_active)"))
    connection.execute(
        text("CREATE INDEX idx_reading_session_session_key ON reading_sessions(session_key)")
    )
    connection.execute(
        text("CREATE INDEX idx_reading_session_started_at ON reading_sessions(started_at)")
    )
    connection.execute(
        text("CREATE INDEX idx_reading_session_last_activity ON reading_sessions(last_activity_at)")
    )

    logger.info("Successfully created 'reading_sessions' table with indexes")


def downgrade(connection):
    """Remove the reading_sessions table."""
    logger.info("Dropping 'reading_sessions' table...")
    connection.execute(text("DROP TABLE IF EXISTS reading_sessions CASCADE"))
    logger.info("Successfully dropped 'reading_sessions' table")