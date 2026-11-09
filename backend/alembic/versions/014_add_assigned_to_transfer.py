"""add assigned_to_id to transfers

Revision ID: 014_add_assigned_to_transfer
Revises: 013_add_purchase_indent
Create Date: 2026-04-21

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "014_add_assigned_to_transfer"
down_revision = "013_add_purchase_indent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transfers", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "assigned_to_id",
                sa.String(36),
                sa.ForeignKey("users.id"),
                nullable=True,
            )
        )
        batch_op.create_index("ix_transfers_assigned_to_id", ["assigned_to_id"])


def downgrade() -> None:
    with op.batch_alter_table("transfers", schema=None) as batch_op:
        batch_op.drop_index("ix_transfers_assigned_to_id")
        batch_op.drop_column("assigned_to_id")
