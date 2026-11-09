"""Add entity_type and entity_id to attachments

Revision ID: 011_add_attachment_entity_fields
Revises: 010_add_evaluation_fields
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa

revision = "011_add_attachment_entity_fields"
down_revision = "010_add_evaluation_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("entity_type", sa.String(50), nullable=True))
    op.add_column("attachments", sa.Column("entity_id", sa.String(36), nullable=True))
    op.create_index("ix_attachments_entity_type", "attachments", ["entity_type"])
    op.create_index("ix_attachments_entity_id", "attachments", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_attachments_entity_id", "attachments")
    op.drop_index("ix_attachments_entity_type", "attachments")
    op.drop_column("attachments", "entity_id")
    op.drop_column("attachments", "entity_type")
