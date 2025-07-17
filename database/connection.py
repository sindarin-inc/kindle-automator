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
        self.schema_name = os.getenv("KINDLE_SCHEMA", "kindle_automator")
        self.engine = None
        self.SessionLocal = None
        self._initialized = False

    def initialize(self):
        """Initialize the database connection and session factory."""
        if self._initialized:
            return

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

        # Set up search_path for the schema
        @event.listens_for(self.engine, "connect")
        def set_search_path(dbapi_conn, connection_record):
            with dbapi_conn.cursor() as cursor:
                cursor.execute(f"SET search_path TO {self.schema_name}, public")

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
        """Create the schema if it doesn't exist."""
        if not self._initialized:
            self.initialize()

        with self.engine.connect() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self.schema_name}"))
            conn.commit()
            logger.info(f"Schema {self.schema_name} created or already exists")

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


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function for getting database sessions in Flask routes.
    
    Usage in Flask:
        with get_db() as session:
            # Use session
    """
    with db_connection.get_session() as session:
        yield session