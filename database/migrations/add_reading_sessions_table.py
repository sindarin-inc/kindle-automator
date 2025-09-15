"""Migration to add the reading_sessions table for tracking complete reading sessions."""

import logging

from sqlalchemy import create_engine, inspect, text

logger = logging.getLogger(__name__)


def migrate(database_url: str):
    """Add the reading_sessions table for tracking reading sessions."""
    engine = create_engine(database_url)

    with engine.connect() as connection:
        inspector = inspect(engine)

        # Check if table already exists
        if "reading_sessions" in inspector.get_table_names():
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

        connection.commit()

        logger.info("Successfully created 'reading_sessions' table with indexes")


if __name__ == "__main__":
    # For local testing
    import os

    from dotenv import load_dotenv

    load_dotenv()
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        print("DATABASE_URL not found in environment variables")
        exit(1)

    migrate(database_url)
    print("Migration completed successfully")
