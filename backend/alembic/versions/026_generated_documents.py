"""add generated documents table

Revision ID: 026_generated_documents
Revises: 025_branding_and_asset_purchase_fields
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa


revision = "026_generated_documents"
down_revision = "025_branding_and_asset_purchase_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("reference_number", sa.String(length=120), nullable=False),
        sa.Column("related_entity_type", sa.String(length=50), nullable=True),
        sa.Column("related_entity_id", sa.String(length=36), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("generated_by_id", sa.String(length=36), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_batch_id", sa.String(length=80), nullable=True),
        sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generated_documents_document_type", "generated_documents", ["document_type"])
    op.create_index("ix_generated_documents_reference_number", "generated_documents", ["reference_number"])
    op.create_index("ix_generated_documents_related_entity_type", "generated_documents", ["related_entity_type"])
    op.create_index("ix_generated_documents_related_entity_id", "generated_documents", ["related_entity_id"])
    op.create_index("ix_generated_documents_period_start", "generated_documents", ["period_start"])
    op.create_index("ix_generated_documents_period_end", "generated_documents", ["period_end"])
    op.create_index("ix_generated_documents_generated_at", "generated_documents", ["generated_at"])
    op.create_index("ix_generated_documents_expires_at", "generated_documents", ["expires_at"])
    op.create_index("ix_generated_documents_email_batch_id", "generated_documents", ["email_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_generated_documents_email_batch_id", table_name="generated_documents")
    op.drop_index("ix_generated_documents_expires_at", table_name="generated_documents")
    op.drop_index("ix_generated_documents_generated_at", table_name="generated_documents")
    op.drop_index("ix_generated_documents_period_end", table_name="generated_documents")
    op.drop_index("ix_generated_documents_period_start", table_name="generated_documents")
    op.drop_index("ix_generated_documents_related_entity_id", table_name="generated_documents")
    op.drop_index("ix_generated_documents_related_entity_type", table_name="generated_documents")
    op.drop_index("ix_generated_documents_reference_number", table_name="generated_documents")
    op.drop_index("ix_generated_documents_document_type", table_name="generated_documents")
    op.drop_table("generated_documents")

