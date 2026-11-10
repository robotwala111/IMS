"""Add missing indexes for foreign keys

Revision ID: 028_add_missing_foreign_key_indexes
Revises: 027_enable_rls_new_public_tables
Create Date: 2026-07-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "028_add_missing_foreign_key_indexes"
down_revision: Union[str, None] = "027_enable_rls_new_public_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = (
    ("ix_attachments_uploaded_by_id", "attachments", "uploaded_by_id"),
    ("ix_calibration_records_attachment_id", "calibration_records", "attachment_id"),
    ("ix_calibration_records_recorded_by_id", "calibration_records", "recorded_by_id"),
    (
        "ix_calibration_supplier_transactions_recorded_by_id",
        "calibration_supplier_transactions",
        "recorded_by_id",
    ),
    ("ix_generated_documents_generated_by_id", "generated_documents", "generated_by_id"),
    ("ix_jobs_assigned_to_id", "jobs", "assigned_to_id"),
    ("ix_jobs_completed_by_id", "jobs", "completed_by_id"),
    ("ix_jobs_created_by_id", "jobs", "created_by_id"),
    ("ix_maintenance_records_assigned_to_id", "maintenance_records", "assigned_to_id"),
    ("ix_maintenance_records_attachment_id", "maintenance_records", "attachment_id"),
    ("ix_maintenance_records_completed_by_id", "maintenance_records", "completed_by_id"),
    ("ix_purchase_indent_items_item_id", "purchase_indent_items", "item_id"),
    ("ix_purchase_indents_approved_by_id", "purchase_indents", "approved_by_id"),
    ("ix_purchase_indents_requested_by_id", "purchase_indents", "requested_by_id"),
    ("ix_serialized_assets_assigned_to_user_id", "serialized_assets", "assigned_to_user_id"),
    ("ix_transactions_asset_id", "transactions", "asset_id"),
    ("ix_transactions_created_by_id", "transactions", "created_by_id"),
    ("ix_transactions_lot_id", "transactions", "lot_id"),
    ("ix_transfer_items_item_id", "transfer_items", "item_id"),
    ("ix_transfers_approved_by_id", "transfers", "approved_by_id"),
    ("ix_transfers_received_by_id", "transfers", "received_by_id"),
    ("ix_transfers_requested_by_id", "transfers", "requested_by_id"),
    ("ix_transfers_shipped_by_id", "transfers", "shipped_by_id"),
    ("ix_user_locations_location_id", "user_locations", "location_id"),
)


def upgrade() -> None:
    for index_name, table_name, column_name in INDEXES:
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON public.{table_name} ({column_name})"
        )


def downgrade() -> None:
    for index_name, _, _ in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS public.{index_name}")
