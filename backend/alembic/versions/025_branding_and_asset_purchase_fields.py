"""Add branding and serialized asset purchase fields

Revision ID: 025_branding_and_asset_purchase_fields
Revises: 024_enable_rls_public_tables
Create Date: 2026-06-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "025_branding_and_asset_purchase_fields"
down_revision: Union[str, None] = "024_enable_rls_public_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("serialized_assets", sa.Column("supplier_name", sa.String(length=255), nullable=True))
    op.add_column("serialized_assets", sa.Column("invoice_number", sa.String(length=100), nullable=True))

    op.create_table(
        "app_branding",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("app_name", sa.String(length=100), nullable=False),
        sa.Column("logo_data_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "INSERT INTO app_branding (id, company_name, app_name, logo_data_url) "
        "VALUES ('default', 'M/s. SCIENTECH SERVICES', 'Scientech-IMS', NULL)"
    )


def downgrade() -> None:
    op.drop_table("app_branding")
    op.drop_column("serialized_assets", "invoice_number")
    op.drop_column("serialized_assets", "supplier_name")

