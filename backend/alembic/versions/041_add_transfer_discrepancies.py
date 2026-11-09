"""Track damaged and lost quantities during transfer receipt."""

from alembic import op
import sqlalchemy as sa

revision = "041_transfer_discrepancies"
down_revision = "040_personnel_revocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transfer_items",
        sa.Column("quantity_damaged", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "transfer_items",
        sa.Column("quantity_lost", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_transfer_items_nonnegative_disposition",
        "transfer_items",
        "quantity_received >= 0 AND quantity_damaged >= 0 AND quantity_lost >= 0",
    )
    op.create_check_constraint(
        "ck_transfer_items_disposition_within_request",
        "transfer_items",
        "quantity_received + quantity_damaged + quantity_lost <= quantity_requested",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_transfer_items_disposition_within_request", "transfer_items", type_="check"
    )
    op.drop_constraint(
        "ck_transfer_items_nonnegative_disposition", "transfer_items", type_="check"
    )
    op.drop_column("transfer_items", "quantity_lost")
    op.drop_column("transfer_items", "quantity_damaged")
