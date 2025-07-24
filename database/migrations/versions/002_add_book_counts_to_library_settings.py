"""Add book count columns to library_settings

Revision ID: 002
Revises: 001
Create Date: 2025-07-24

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add filter_book_count column
    op.add_column(
        "library_settings",
        sa.Column("filter_book_count", sa.Integer(), nullable=True),
        schema="kindle_automator",
    )

    # Add scroll_book_count column
    op.add_column(
        "library_settings",
        sa.Column("scroll_book_count", sa.Integer(), nullable=True),
        schema="kindle_automator",
    )


def downgrade() -> None:
    # Remove scroll_book_count column
    op.drop_column("library_settings", "scroll_book_count", schema="kindle_automator")

    # Remove filter_book_count column
    op.drop_column("library_settings", "filter_book_count", schema="kindle_automator")
