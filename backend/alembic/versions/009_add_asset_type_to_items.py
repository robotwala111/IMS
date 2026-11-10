"""Add asset_type column to items table

Revision ID: 009_add_asset_type
Revises: 008_return_reminder_days
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "009_add_asset_type"
down_revision = "008_return_reminder_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("asset_type", sa.String(50), nullable=True, server_default="equipment"))
    op.create_index("ix_items_asset_type", "items", ["asset_type"])


def downgrade() -> None:
    op.drop_index("ix_items_asset_type", table_name="items")
    op.drop_column("items", "asset_type")
