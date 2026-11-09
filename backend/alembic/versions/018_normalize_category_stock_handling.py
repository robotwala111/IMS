"""Normalize standard category stock handling.

Revision ID: 018_normalize_cats
Revises: 017_seed_standard_categories
Create Date: 2026-06-01
"""

from typing import Sequence, Union

from alembic import op


revision: str = "018_normalize_cats"
down_revision: Union[str, Sequence[str], None] = "017_seed_standard_categories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE category_types
        SET stock_behavior = 'serialized', updated_at = CURRENT_TIMESTAMP
        WHERE key IN ('equipment', 'instrument')
        """
    )
    op.execute(
        """
        UPDATE category_types
        SET stock_behavior = 'quantity', updated_at = CURRENT_TIMESTAMP
        WHERE key IN ('consumable', 'accessory')
        """
    )
    op.execute(
        """
        UPDATE categories
        SET category_type_id = 'category-type-accessory', updated_at = CURRENT_TIMESTAMP
        WHERE lower(name) IN ('accessory', 'accessories')
        """
    )
    op.execute(
        """
        UPDATE categories
        SET category_type_id = 'category-type-consumable', updated_at = CURRENT_TIMESTAMP
        WHERE lower(name) IN ('consumable', 'consumables')
        """
    )
    op.execute(
        """
        UPDATE categories
        SET category_type_id = 'category-type-equipment', updated_at = CURRENT_TIMESTAMP
        WHERE lower(name) IN ('equipment', 'equipments')
        """
    )
    op.execute(
        """
        UPDATE categories
        SET category_type_id = 'category-type-instrument', updated_at = CURRENT_TIMESTAMP
        WHERE lower(name) IN ('instrument', 'instruments')
        """
    )


def downgrade() -> None:
    pass
