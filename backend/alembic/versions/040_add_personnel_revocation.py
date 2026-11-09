"""Record explicit personnel certificate and qualification revocations."""

from alembic import op
import sqlalchemy as sa

revision = "040_personnel_revocation"
down_revision = "039_return_disposition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("employee_records", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("employee_records", sa.Column("revocation_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_employee_records_revocation_complete",
        "employee_records",
        "(revoked_at IS NULL AND revocation_reason IS NULL) OR "
        "(revoked_at IS NOT NULL AND length(trim(revocation_reason)) > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_employee_records_revocation_complete", "employee_records", type_="check")
    op.drop_column("employee_records", "revocation_reason")
    op.drop_column("employee_records", "revoked_at")
