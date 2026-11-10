"""Add employees table and make employee_records.user_id nullable with employee_id FK

Revision ID: 014_add_employees_table
Revises: 013_add_purchase_indent
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa

revision = "014_add_employees_table"
down_revision = "013_add_purchase_indent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create the employees table
    op.create_table(
        "employees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("employee_code", sa.String(50), nullable=True, unique=True),
        sa.Column("designation", sa.String(100), nullable=True),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("location_id", sa.String(36), sa.ForeignKey("locations.id"), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_employees_name", "employees", ["name"])
    op.create_index("ix_employees_location_id", "employees", ["location_id"])

    # 2. Add employee_id FK to employee_records
    op.add_column(
        "employee_records",
        sa.Column("employee_id", sa.String(36), sa.ForeignKey("employees.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_employee_records_employee_id", "employee_records", ["employee_id"])

    # 3. Make user_id nullable (was NOT NULL before)
    op.alter_column("employee_records", "user_id", nullable=True)


def downgrade() -> None:
    # Reverse: restore user_id NOT NULL (will fail if employee-only records exist)
    op.alter_column("employee_records", "user_id", nullable=False)
    op.drop_index("ix_employee_records_employee_id", "employee_records")
    op.drop_column("employee_records", "employee_id")
    op.drop_index("ix_employees_location_id", "employees")
    op.drop_index("ix_employees_name", "employees")
    op.drop_table("employees")
