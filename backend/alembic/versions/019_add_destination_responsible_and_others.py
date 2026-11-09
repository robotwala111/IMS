"""Add destination responsible person and Others category type.

Revision ID: 019_destination_responsible_others
Revises: 018_normalize_cats
Create Date: 2026-06-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019_destination_responsible_others"
down_revision: Union[str, Sequence[str], None] = "018_normalize_cats"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transfers",
        sa.Column("destination_responsible_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_transfers_destination_responsible_id",
        "transfers",
        ["destination_responsible_id"],
    )
    op.create_foreign_key(
        "fk_transfers_destination_responsible_id_users",
        "transfers",
        "users",
        ["destination_responsible_id"],
        ["id"],
    )

    op.execute(
        """
        INSERT INTO category_types
            (id, key, name, stock_behavior, is_active, created_at, updated_at)
        VALUES
            ('category-type-others', 'others', 'Others', 'quantity', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT (key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM category_types WHERE id = 'category-type-others'")
    op.drop_constraint(
        "fk_transfers_destination_responsible_id_users",
        "transfers",
        type_="foreignkey",
    )
    op.drop_index("ix_transfers_destination_responsible_id", table_name="transfers")
    op.drop_column("transfers", "destination_responsible_id")
