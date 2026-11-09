"""Add immutable generated-document revision numbers."""

from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "034_add_document_revisions"
down_revision: Union[str, None] = "033_add_stock_quantity_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "generated_documents",
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_generated_documents_reference_revision",
        "generated_documents",
        ["document_type", "reference_number", "revision_number"],
    )

def downgrade() -> None:
    op.drop_index("ix_generated_documents_reference_revision", table_name="generated_documents")
    op.drop_column("generated_documents", "revision_number")
