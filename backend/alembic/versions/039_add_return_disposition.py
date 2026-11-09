"""Track whether returned stock is serviceable or quarantined."""

from alembic import op
import sqlalchemy as sa

revision = "039_return_disposition"
down_revision = "038_return_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("return_condition", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_transactions_return_condition",
        "transactions",
        "return_condition IS NULL OR return_condition IN ('good', 'damaged', 'expired')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transactions_return_condition", "transactions", type_="check")
    op.drop_column("transactions", "return_condition")
