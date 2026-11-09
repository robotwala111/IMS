"""Allow inventory items without a Product Code/SKU.

Revision ID: 031_make_item_sku_optional
Revises: 030_add_delivery_challan_number
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031_make_item_sku_optional"
down_revision: Union[str, None] = "030_add_delivery_challan_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "items",
        "sku",
        existing_type=sa.String(length=50),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE items SET sku = 'LEGACY-' || id WHERE sku IS NULL")
    op.alter_column(
        "items",
        "sku",
        existing_type=sa.String(length=50),
        nullable=False,
    )
