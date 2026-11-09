"""Add jobs table

Revision ID: 012_add_jobs_table
Revises: 011_add_attachment_entity_fields
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa

revision = "012_add_jobs_table"
down_revision = "011_add_attachment_entity_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_number", sa.String(50), unique=True, index=True, nullable=False),
        sa.Column("job_date", sa.Date(), nullable=False),
        sa.Column("customer", sa.String(255), nullable=False),
        sa.Column("job_name", sa.String(255), nullable=False),
        sa.Column("method", sa.String(50), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage", sa.String(100), nullable=True),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("person_name", sa.String(255), nullable=False),
        sa.Column("assigned_to_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("location_id", sa.String(36), sa.ForeignKey("locations.id"), nullable=True, index=True),
        sa.Column(
            "status",
            sa.Enum("hold", "in_progress", "completed", "verified", name="jobstatus"),
            nullable=False,
            server_default="hold",
        ),
        sa.Column("completed_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted", sa.Integer(), nullable=True),
        sa.Column("reshoot", sa.Integer(), nullable=True),
        sa.Column("cut_films", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_validated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", "jobs")
    op.drop_table("jobs")
