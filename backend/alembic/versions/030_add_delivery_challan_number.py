"""Add persistent Delivery Challan number.

Revision ID: 030_add_delivery_challan_number
Revises: 029_add_stock_active_state
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_add_delivery_challan_number"
down_revision: Union[str, None] = "029_add_stock_active_state"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("transfers", sa.Column("dc_number", sa.String(length=50), nullable=True))
    op.create_index("ix_transfers_dc_number", "transfers", ["dc_number"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_transfers_dc_number", table_name="transfers")
    op.drop_column("transfers", "dc_number")
