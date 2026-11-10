"""Enable row level security on public tables

Revision ID: 024_enable_rls_public_tables
Revises: 023_remove_location_user_role
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "024_enable_rls_public_tables"
down_revision: Union[str, None] = "023_remove_location_user_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "category_types",
    "notifications",
    "audit_logs",
    "users",
    "locations",
    "user_locations",
    "categories",
    "attachments",
    "employees",
    "jobs",
    "transfers",
    "employee_records",
    "alembic_version",
    "item_attributes",
    "items",
    "purchase_indents",
    "purchase_indent_items",
    "serialized_assets",
    "stock_lots",
    "stocks",
    "transfer_items",
    "calibration_records",
    "calibration_supplier_transactions",
    "maintenance_records",
    "transactions",
)


def _alter_rls(enable: bool) -> None:
    action = "ENABLE" if enable else "DISABLE"
    table_list = ", ".join(f"'{table}'" for table in TABLES)
    op.execute(
        f"""
        DO $$
        DECLARE
            table_name text;
        BEGIN
            FOREACH table_name IN ARRAY ARRAY[{table_list}]
            LOOP
                IF to_regclass('public.' || table_name) IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE public.%I {action} ROW LEVEL SECURITY', table_name);
                END IF;
            END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    _alter_rls(enable=True)


def downgrade() -> None:
    _alter_rls(enable=False)
