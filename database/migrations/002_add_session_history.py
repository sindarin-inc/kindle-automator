#!/usr/bin/env python3
"""Migration to add previous session tracking columns to book_sessions table."""

import logging
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import text
from database.connection import get_db

logger = logging.getLogger(__name__)


def migrate():
    """Add previous_session_key and previous_position columns to book_sessions table."""
    
    with get_db() as session:
        try:
            # Check if columns already exist
            result = session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'book_sessions' 
                AND column_name IN ('previous_session_key', 'previous_position')
            """))
            existing_columns = [row[0] for row in result]
            
            # Add previous_session_key if it doesn't exist
            if 'previous_session_key' not in existing_columns:
                session.execute(text("""
                    ALTER TABLE book_sessions 
                    ADD COLUMN previous_session_key VARCHAR(255)
                """))
                logger.info("Added previous_session_key column to book_sessions table")
            else:
                logger.info("previous_session_key column already exists")
            
            # Add previous_position if it doesn't exist
            if 'previous_position' not in existing_columns:
                session.execute(text("""
                    ALTER TABLE book_sessions 
                    ADD COLUMN previous_position INTEGER
                """))
                logger.info("Added previous_position column to book_sessions table")
            else:
                logger.info("previous_position column already exists")
            
            session.commit()
            logger.info("Migration completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            session.rollback()
            return False


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run migration
    success = migrate()
    sys.exit(0 if success else 1)