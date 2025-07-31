"""Database connection and session management using SQLAlchemy 2.0."""

import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

logger = logging.getLogger(__name__)


class DatabaseConnection:
    """Manages database connections and sessions for the Kindle Automator."""

    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        self.schema_name = "public"
        self.engine = None
        self.SessionLocal = None
        self._initialized = False

    def initialize(self):
        """Initialize the database connection and session factory."""
        if self._initialized:
            return

        # Try to get DATABASE_URL again in case it wasn't available when __init__ was called
        if not self.database_url:
            self.database_url = os.getenv("DATABASE_URL")

        if not self.database_url:
            raise ValueError("DATABASE_URL environment variable is not set")

        # Determine if we're in development or production
        is_development = os.getenv("FLASK_ENV") == "development"

        # Configure connection pool based on environment
        if is_development:
            # Use NullPool for development to avoid connection issues
            self.engine = create_engine(
                self.database_url,
                poolclass=NullPool,
                echo=False,  # Set to True for SQL query logging
                future=True,  # Use SQLAlchemy 2.0 style
            )
        else:
            # Use QueuePool for production with proper sizing
            self.engine = create_engine(
                self.database_url,
                poolclass=QueuePool,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=1800,  # Recycle connections after 30 minutes
                echo=False,
                future=True,
            )

        # No need to set search_path since we're using public schema

        # Create session factory
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

        self._initialized = True
        logger.info(f"Database connection initialized with schema: {self.schema_name}")

    def create_schema(self):
        """No longer needed - using public schema."""
        pass

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Get a database session with automatic cleanup.

        Usage:
            with db.get_session() as session:
                # Use session here
                session.commit()  # Commit when needed
        """
        if not self._initialized:
            self.initialize()

        session = self.SessionLocal()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self):
        """Dispose of the connection pool."""
        if self.engine:
            self.engine.dispose()
            logger.info("Database connection pool disposed")


# Global database connection instance
db_connection = DatabaseConnection()


def get_db():
    """
    Get a database session context manager.

    Usage:
        with get_db() as session:
            # Use session
    """
    return db_connection.get_session()
