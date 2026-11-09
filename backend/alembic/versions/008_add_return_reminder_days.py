"""Add return_reminder_days to transfers

Revision ID: 008_return_reminder_days
Revises: 007_maintenance_interval
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa

revision = "008_return_reminder_days"
down_revision = "007_maintenance_interval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transfers", sa.Column("return_reminder_days", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("transfers", "return_reminder_days")
