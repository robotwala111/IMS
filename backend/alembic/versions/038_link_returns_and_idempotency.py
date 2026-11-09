"""Link returns to issues and support idempotent return requests."""

from alembic import op
import sqlalchemy as sa

revision = "038_return_integrity"
down_revision = "037_job_cut_films_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("idempotency_key", sa.String(100), nullable=True))
    op.add_column("transactions", sa.Column("idempotency_line", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        "uq_transaction_idempotency_line", "transactions", ["idempotency_key", "idempotency_line"]
    )
    op.create_index(
        "ix_transactions_return_issue", "transactions", ["reference_type", "reference_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_return_issue", table_name="transactions")
    op.drop_constraint("uq_transaction_idempotency_line", "transactions", type_="unique")
    op.drop_column("transactions", "idempotency_line")
    op.drop_column("transactions", "idempotency_key")
