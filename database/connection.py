"""Database connection and session management using SQLAlchemy 2.0."""

import logging
import os
import re
import time
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, QueuePool

from server.utils.ansi_colors import (
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    DIM_GRAY,
    GRAY,
    RED,
    RESET,
    YELLOW,
)

logger = logging.getLogger(__name__)

# Global flag to track if query logging is already set up
# Reset to False to ensure new color scheme is picked up on restart
_query_logging_initialized = False


def format_sql_query(query: str) -> str:
    """Format SQL query for pretty logging, simplifying long SELECT statements."""
    # Remove extra whitespace and newlines
    query = re.sub(r"\s+", " ", query).strip()

    # If it's a SELECT with many columns, simplify to SELECT *
    if query.upper().startswith("SELECT"):
        # Match SELECT ... FROM pattern
        match = re.match(r"(SELECT\s+)(.*?)(\s+FROM\s+.*)", query, re.IGNORECASE | re.DOTALL)
        if match:
            select_clause = match.group(2)
            # If the select clause is very long, replace with *
            if len(select_clause) > 50 or select_clause.count(",") > 3:
                query = f"{match.group(1)}*{match.group(3)}"

    return query


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

        # Add query logging for development environment
        # Can be disabled by setting SQL_LOGGING=false or SQL_LOGGING=0
        sql_logging_enabled = os.getenv("SQL_LOGGING", "true").lower() not in ["false", "0", "no", "off"]

        # Enable SQL logging for development and staging environments
        environment = os.getenv("ENVIRONMENT", "").lower()
        if (is_development or environment in ["dev", "staging"]) and sql_logging_enabled:
            self._setup_query_logging()
            logger.debug("SQL query logging enabled (set SQL_LOGGING=false to disable)")

        self._initialized = True
        logger.debug(f"Database connection initialized with schema: {self.schema_name}")

    def create_schema(self):
        """No longer needed - using public schema."""
        pass

    def _setup_query_logging(self):
        """Set up SQL query logging with timing for development environment."""
        global _query_logging_initialized

        # Only set up logging once globally
        if _query_logging_initialized:
            return

        _query_logging_initialized = True
        query_times = {}

        @event.listens_for(Engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault("query_start_time", []).append(time.time())
            # Store the statement for later use
            conn.info.setdefault("current_statement", []).append(statement)

        @event.listens_for(Engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            total_time = time.time() - conn.info["query_start_time"].pop(-1)

            # Render the query with actual parameter values
            rendered_query = statement
            if parameters:
                # SQLAlchemy passes parameters differently for different dialects
                # For PostgreSQL with psycopg2, we need to handle both dict and tuple formats
                try:
                    if hasattr(parameters, "keys"):  # Dict-like object
                        # Handle named parameters
                        for key, value in parameters.items():
                            placeholder = f"%({key})s"
                            if placeholder in rendered_query:
                                # Quote strings and handle None
                                if value is None:
                                    rendered_value = "NULL"
                                elif isinstance(value, str):
                                    # Escape single quotes in strings
                                    rendered_value = f"'{value.replace('\'', '\'\'')}'"
                                elif isinstance(value, (int, float)):
                                    rendered_value = str(value)
                                elif isinstance(value, (list, tuple)):
                                    # Handle IN clause parameters
                                    values = []
                                    for v in value:
                                        if isinstance(v, str):
                                            values.append(f"'{v}'")
                                        else:
                                            values.append(str(v))
                                    rendered_value = f"({', '.join(values)})"
                                else:
                                    rendered_value = str(value)
                                rendered_query = rendered_query.replace(placeholder, rendered_value)
                    else:  # Tuple/list
                        # Handle positional parameters
                        if isinstance(parameters, (list, tuple)):
                            for value in parameters:
                                if value is None:
                                    rendered_value = "NULL"
                                elif isinstance(value, str):
                                    rendered_value = f"'{value.replace('\'', '\'\'')}'"
                                elif isinstance(value, (int, float)):
                                    rendered_value = str(value)
                                else:
                                    rendered_value = str(value)
                                # Replace the first %s
                                rendered_query = rendered_query.replace("%s", rendered_value, 1)
                except Exception as e:
                    # If rendering fails, just use the original query
                    logger.debug(f"Failed to render query parameters: {e}")
                    rendered_query = statement

            # Format the query
            formatted_query = format_sql_query(rendered_query)

            # Determine color based on query type
            if statement.upper().startswith("SELECT"):
                query_color = YELLOW
            elif statement.upper().startswith("UPDATE"):
                query_color = BRIGHT_CYAN
            elif statement.upper().startswith(("INSERT", "DELETE")):
                query_color = BRIGHT_GREEN
            else:
                query_color = DIM_GRAY

            # Format timing with color based on performance
            time_ms = total_time * 1000
            if time_ms > 20:  # Red for queries > 20ms
                time_str = f"{RED}{time_ms:.1f}ms{RESET}"
            elif time_ms > 10:  # Light gray for queries > 10ms
                time_str = f"{GRAY}{time_ms:.1f}ms{RESET}"
            else:  # Dim gray for fast queries
                time_str = f"{DIM_GRAY}{time_ms:.1f}ms{RESET}"

            # Log the query at debug level
            logger.debug(f"[SQL {time_str}] {query_color}{formatted_query}{RESET}")

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
