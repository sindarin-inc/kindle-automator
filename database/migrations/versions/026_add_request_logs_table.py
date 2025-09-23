"""Add request_logs table for tracking all HTTP requests

Revision ID: 026
Revises: 025
Create Date: 2025-09-23
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    """Add the request_logs table for tracking all HTTP requests."""
    # Check if table already exists (for idempotency)
    conn = op.get_bind()
    result = conn.execute(
        sa.text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'request_logs')")
    )
    table_exists = result.scalar()

    if table_exists:
        print("Table 'request_logs' already exists, skipping creation")
        return

    print("Creating 'request_logs' table...")

    # Create the table
    conn.execute(
        sa.text(
            """
        CREATE TABLE request_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            datetime TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            method VARCHAR(10) NOT NULL,
            path VARCHAR(500) NOT NULL,
            params TEXT,
            user_agent TEXT,
            user_agent_identifier VARCHAR(50),
            status_code INTEGER NOT NULL,
            elapsed_time REAL,
            response_length INTEGER,
            response_preview VARCHAR(500),
            ip_address VARCHAR(45),
            referer TEXT,
            is_ajax BOOLEAN NOT NULL DEFAULT FALSE,
            is_mobile BOOLEAN NOT NULL DEFAULT FALSE,
            user_email VARCHAR(255)
        )
    """
        )
    )

    # Create indexes
    conn.execute(sa.text("CREATE INDEX idx_request_log_datetime ON request_logs(datetime)"))
    conn.execute(sa.text("CREATE INDEX idx_request_log_user_datetime ON request_logs(user_id, datetime)"))
    conn.execute(sa.text("CREATE INDEX idx_request_log_path ON request_logs(path)"))
    conn.execute(sa.text("CREATE INDEX idx_request_log_path_datetime ON request_logs(path, datetime)"))
    conn.execute(sa.text("CREATE INDEX idx_request_log_status_code ON request_logs(status_code)"))
    conn.execute(
        sa.text("CREATE INDEX idx_request_log_status_datetime ON request_logs(status_code, datetime)")
    )
    conn.execute(
        sa.text("CREATE INDEX idx_request_log_user_agent_identifier ON request_logs(user_agent_identifier)")
    )
    conn.execute(sa.text("CREATE INDEX idx_request_log_user_email ON request_logs(user_email)"))

    print("Successfully created 'request_logs' table with indexes")


def downgrade():
    """Remove the request_logs table."""
    print("Dropping 'request_logs' table...")
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS request_logs CASCADE"))
    print("Successfully dropped 'request_logs' table")
