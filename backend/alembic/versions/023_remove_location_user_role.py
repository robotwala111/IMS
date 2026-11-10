"""Remove legacy location_user role

Revision ID: 023_remove_location_user_role
Revises: 022_add_calibration_supplier_transactions
Create Date: 2026-06-16
"""

from typing import Sequence, Union

from alembic import op


revision: str = "023_remove_location_user_role"
down_revision: Union[str, None] = "022_add_calibration_supplier_transactions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_enum e ON e.enumtypid = t.oid
                WHERE t.typname = 'userrole'
                  AND e.enumlabel = 'LOCATION_MANAGER'
            ) THEN
                UPDATE users
                SET role = 'LOCATION_MANAGER'
                WHERE role::text IN ('LOCATION_USER', 'location_user');
            ELSE
                UPDATE users
                SET role = 'location_manager'
                WHERE role::text IN ('LOCATION_USER', 'location_user');
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # The old role cannot be restored safely because the original affected users
    # are intentionally normalized to Location Manager during upgrade.
    pass
