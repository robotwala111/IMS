"""Add purchase_indents table and link transfer to PI

Revision ID: 013_add_purchase_indent
Revises: 012_add_jobs_table
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "013_add_purchase_indent"
down_revision = "012_add_jobs_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    existing_tables = {row[0] for row in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}

    # ---------------------------------------------------------------
    # 1. purchase_indents master table
    # ---------------------------------------------------------------
    if "purchase_indents" not in existing_tables:
        op.create_table(
            "purchase_indents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("indent_number", sa.String(50), unique=True, index=True, nullable=False),
            sa.Column(
                "requested_by_location_id",
                sa.String(36),
                sa.ForeignKey("locations.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "supplying_location_id",
                sa.String(36),
                sa.ForeignKey("locations.id"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "status",
                sa.String(30),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "requested_by_id",
                sa.String(36),
                sa.ForeignKey("users.id"),
                nullable=False,
            ),
            sa.Column(
                "approved_by_id",
                sa.String(36),
                sa.ForeignKey("users.id"),
                nullable=True,
            ),
            sa.Column("indent_date", sa.DateTime(timezone=True), nullable=False),
            sa.Column("required_by_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("purpose", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index("ix_purchase_indents_status", "purchase_indents", ["status"])

    # ---------------------------------------------------------------
    # 2. purchase_indent_items line table
    # ---------------------------------------------------------------
    if "purchase_indent_items" not in existing_tables:
        op.create_table(
            "purchase_indent_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "indent_id",
                sa.String(36),
                sa.ForeignKey("purchase_indents.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "item_id",
                sa.String(36),
                sa.ForeignKey("items.id"),
                nullable=False,
            ),
            sa.Column("quantity_requested", sa.Integer(), nullable=False),
            sa.Column("quantity_approved", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("quantity_fulfilled", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    # ---------------------------------------------------------------
    # 3. Link transfers -> purchase_indent
    #    SQLite does not support FK in ALTER TABLE.
    #    Guard against columns already existing (from partial prior runs).
    # ---------------------------------------------------------------
    existing_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(transfers)")).fetchall()}

    if "purchase_indent_id" not in existing_cols:
        op.add_column(
            "transfers",
            sa.Column("purchase_indent_id", sa.String(36), nullable=True),
        )
    if "purchase_indent_number" not in existing_cols:
        op.add_column(
            "transfers",
            sa.Column("purchase_indent_number", sa.String(50), nullable=True),
        )

    # Create indexes (ignore if already exist)
    existing_indexes = {row[1] for row in conn.execute(sa.text("SELECT * FROM sqlite_master WHERE type='index'")).fetchall()}
    if "ix_transfers_purchase_indent_id" not in existing_indexes:
        op.create_index("ix_transfers_purchase_indent_id", "transfers", ["purchase_indent_id"])
    if "ix_transfers_purchase_indent_number" not in existing_indexes:
        op.create_index("ix_transfers_purchase_indent_number", "transfers", ["purchase_indent_number"])


def downgrade() -> None:
    op.drop_index("ix_transfers_purchase_indent_number", table_name="transfers")
    op.drop_index("ix_transfers_purchase_indent_id", table_name="transfers")
    op.drop_column("transfers", "purchase_indent_number")
    op.drop_column("transfers", "purchase_indent_id")
    op.drop_table("purchase_indent_items")
    op.drop_index("ix_purchase_indents_status", table_name="purchase_indents")
    op.drop_table("purchase_indents")
    op.execute("DROP TYPE IF EXISTS purchaseindentstatus")
