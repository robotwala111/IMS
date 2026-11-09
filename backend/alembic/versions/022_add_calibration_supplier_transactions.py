"""Add calibration supplier transactions

Revision ID: 022_add_calibration_supplier_transactions
Revises: 021_remove_employee_evaluation_fields
Create Date: 2026-06-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "022_add_calibration_supplier_transactions"
down_revision: Union[str, None] = "021_remove_employee_evaluation_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "calibration_supplier_transactions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("recorded_by_id", sa.String(length=36), nullable=True),
        sa.Column("sent_at", sa.Date(), nullable=False),
        sa.Column("supplier_name", sa.String(length=255), nullable=False),
        sa.Column("received_at", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["serialized_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calibration_supplier_transactions_asset_id", "calibration_supplier_transactions", ["asset_id"])
    op.create_index("ix_calibration_supplier_transactions_sent_at", "calibration_supplier_transactions", ["sent_at"])
    op.create_index("ix_calibration_supplier_transactions_received_at", "calibration_supplier_transactions", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_calibration_supplier_transactions_received_at", table_name="calibration_supplier_transactions")
    op.drop_index("ix_calibration_supplier_transactions_sent_at", table_name="calibration_supplier_transactions")
    op.drop_index("ix_calibration_supplier_transactions_asset_id", table_name="calibration_supplier_transactions")
    op.drop_table("calibration_supplier_transactions")
