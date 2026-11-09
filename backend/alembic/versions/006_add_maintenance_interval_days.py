"""Add maintenance_interval_days to items

Revision ID: 006
Revises: 005
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa

revision = "007_maintenance_interval"
down_revision = "006_return_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("items", sa.Column("maintenance_interval_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "maintenance_interval_days")
