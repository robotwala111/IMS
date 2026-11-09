"""Add stock active state.

Revision ID: 029_add_stock_active_state
Revises: 028_add_missing_foreign_key_indexes
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "029_add_stock_active_state"
down_revision: Union[str, None] = "028_add_missing_foreign_key_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stocks",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("stocks", "is_active")
