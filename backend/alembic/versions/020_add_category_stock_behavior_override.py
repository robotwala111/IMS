"""Add category-level stock behavior override.

Revision ID: 020_category_stock_behavior
Revises: 019_destination_responsible_others
Create Date: 2026-06-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "020_category_stock_behavior"
down_revision: Union[str, Sequence[str], None] = "019_destination_responsible_others"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("stock_behavior", sa.String(length=20), nullable=True),
    )
    op.execute(
        """
        UPDATE categories AS c
        SET stock_behavior = COALESCE(ct.stock_behavior, 'quantity')
        FROM category_types AS ct
        WHERE c.category_type_id = ct.id
        """
    )
    op.execute("UPDATE categories SET stock_behavior = 'quantity' WHERE stock_behavior IS NULL")
    op.alter_column("categories", "stock_behavior", nullable=False)


def downgrade() -> None:
    op.drop_column("categories", "stock_behavior")
