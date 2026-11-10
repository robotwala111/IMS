"""Add evaluation_done and evaluation_date to employee_records

Revision ID: 010_add_evaluation_fields
Revises: 009_add_asset_type
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa

revision = "010_add_evaluation_fields"
down_revision = "009_add_asset_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employee_records", sa.Column("evaluation_done", sa.Boolean(), nullable=False, server_default="0"))
    op.add_column("employee_records", sa.Column("evaluation_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("employee_records", "evaluation_date")
    op.drop_column("employee_records", "evaluation_done")
