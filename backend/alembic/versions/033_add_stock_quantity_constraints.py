"""Add database-level stock quantity invariants."""

from typing import Sequence, Union
from alembic import op

revision: str = "033_add_stock_quantity_constraints"
down_revision: Union[str, None] = "032_add_secure_auth_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINTS = {
    "ck_stock_on_hand_nonnegative": "quantity_on_hand >= 0",
    "ck_stock_reserved_nonnegative": "quantity_reserved >= 0",
    "ck_stock_reserved_not_above_on_hand": "quantity_reserved <= quantity_on_hand",
    "ck_stock_on_order_nonnegative": "quantity_on_order >= 0",
    "ck_stock_min_level_nonnegative": "min_level >= 0",
    "ck_stock_reorder_point_nonnegative": "reorder_point >= 0",
    "ck_stock_reorder_quantity_nonnegative": "reorder_quantity IS NULL OR reorder_quantity >= 0",
    "ck_stock_max_level_nonnegative": "max_level IS NULL OR max_level >= 0",
}

def upgrade() -> None:
    for name, condition in CONSTRAINTS.items():
        op.create_check_constraint(name, "stocks", condition)

def downgrade() -> None:
    for name in reversed(CONSTRAINTS):
        op.drop_constraint(name, "stocks", type_="check")
