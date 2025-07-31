"""Add keyboard_disabled column to emulator_settings

Revision ID: 006
Revises: 005
Create Date: 2025-07-31 13:20:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add keyboard_disabled column with default false
    op.add_column('emulator_settings', 
                  sa.Column('keyboard_disabled', sa.Boolean(), 
                           nullable=False, server_default='false'))


def downgrade() -> None:
    # Remove keyboard_disabled column
    op.drop_column('emulator_settings', 'keyboard_disabled')