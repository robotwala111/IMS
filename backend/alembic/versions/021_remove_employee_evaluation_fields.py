"""Remove employee evaluation fields

Revision ID: 021_remove_employee_evaluation_fields
Revises: 020_category_stock_behavior
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "021_remove_employee_evaluation_fields"
down_revision: Union[str, None] = "020_category_stock_behavior"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("employee_records", "evaluation_date")
    op.drop_column("employee_records", "evaluation_done")


def downgrade() -> None:
    op.add_column("employee_records", sa.Column("evaluation_done", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("employee_records", sa.Column("evaluation_date", sa.Date(), nullable=True))
    op.alter_column("employee_records", "evaluation_done", server_default=None)
