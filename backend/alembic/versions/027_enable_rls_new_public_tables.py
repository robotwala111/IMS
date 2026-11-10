"""Enable RLS on recently added public tables

Revision ID: 027_enable_rls_new_public_tables
Revises: 026_generated_documents
Create Date: 2026-07-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "027_enable_rls_new_public_tables"
down_revision: Union[str, None] = "026_generated_documents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = (
    "app_branding",
    "generated_documents",
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
