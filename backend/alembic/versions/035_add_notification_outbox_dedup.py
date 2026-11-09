"""Add durable notification outbox deduplication keys."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "035_notification_outbox"
down_revision: Union[str, None] = "034_add_document_revisions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("dedup_key", sa.String(length=255), nullable=True))
    op.create_index("ix_notifications_dedup_key", "notifications", ["dedup_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_notifications_dedup_key", table_name="notifications")
    op.drop_column("notifications", "dedup_key")
