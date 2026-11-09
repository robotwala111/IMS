"""Add configurable category types.

Revision ID: 016_add_category_types
Revises: 015_merge_014_heads
Create Date: 2026-06-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016_add_category_types"
down_revision: Union[str, Sequence[str], None] = "015_merge_014_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


category_types = sa.table(
    "category_types",
    sa.column("id", sa.String),
    sa.column("key", sa.String),
    sa.column("name", sa.String),
    sa.column("stock_behavior", sa.String),
    sa.column("is_active", sa.Boolean),
)


def upgrade() -> None:
    op.create_table(
        "category_types",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("stock_behavior", sa.String(length=20), nullable=False, server_default="quantity"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_category_types_key", "category_types", ["key"])

    op.bulk_insert(
        category_types,
        [
            {
                "id": "category-type-equipment",
                "key": "equipment",
                "name": "Equipment",
                "stock_behavior": "serialized",
                "is_active": True,
            },
            {
                "id": "category-type-instrument",
                "key": "instrument",
                "name": "Instrument",
                "stock_behavior": "serialized",
                "is_active": True,
            },
            {
                "id": "category-type-consumable",
                "key": "consumable",
                "name": "Consumable",
                "stock_behavior": "quantity",
                "is_active": True,
            },
            {
                "id": "category-type-accessory",
                "key": "accessory",
                "name": "Accessory",
                "stock_behavior": "quantity",
                "is_active": True,
            },
        ],
    )

    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category_type_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_categories_category_type_id_category_types",
            "category_types",
            ["category_type_id"],
            ["id"],
        )

    op.create_index("ix_categories_category_type_id", "categories", ["category_type_id"])

    op.execute(
        """
        UPDATE categories
        SET category_type_id = 'category-type-equipment'
        WHERE category_type_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_categories_category_type_id", table_name="categories")
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_constraint("fk_categories_category_type_id_category_types", type_="foreignkey")
        batch_op.drop_column("category_type_id")
    op.drop_index("ix_category_types_key", table_name="category_types")
    op.drop_table("category_types")
