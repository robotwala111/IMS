"""Seed standard inventory categories.

Revision ID: 017_seed_standard_categories
Revises: 016_add_category_types
Create Date: 2026-06-01
"""

from typing import Sequence, Union

from alembic import op


revision: str = "017_seed_standard_categories"
down_revision: Union[str, Sequence[str], None] = "016_add_category_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO categories
            (id, name, description, is_active, parent_id, category_type_id, created_at, updated_at)
        VALUES
            ('category-equipment', 'Equipment', 'Serialized NDT equipment tracked one unit per serial number.', true, null, 'category-type-equipment', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('category-instrument', 'Instrument', 'Serialized NDT instruments tracked one unit per serial number.', true, null, 'category-type-instrument', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('category-consumable', 'Consumable', 'Quantity based consumables used during NDT work.', true, null, 'category-type-consumable', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('category-accessory', 'Accessory', 'Quantity based accessories and supporting items.', true, null, 'category-type-accessory', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (name) DO UPDATE
        SET
            category_type_id = EXCLUDED.category_type_id,
            updated_at = CURRENT_TIMESTAMP
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM categories
        WHERE id IN (
            'category-equipment',
            'category-instrument',
            'category-consumable',
            'category-accessory'
        )
        """
    )
