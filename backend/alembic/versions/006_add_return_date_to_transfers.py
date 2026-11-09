"""Add return_date and return_date_modified_reason to transfers

Revision ID: 006_return_date
Revises: 005
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa

revision = "006_return_date"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transfers", sa.Column("return_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("transfers", sa.Column("return_date_modified_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("transfers", "return_date_modified_reason")
    op.drop_column("transfers", "return_date")
