"""Sign audit records and enforce append-only storage."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036_audit_integrity"
down_revision: Union[str, None] = "035_notification_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("integrity_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_audit_logs_integrity_hash", "audit_logs", ["integrity_hash"])

    bind = op.get_bind()
    from app.models.audit import AuditLog

    rows = bind.execute(sa.text("SELECT * FROM audit_logs")).mappings().all()
    model_columns = {column.name for column in AuditLog.__table__.columns}
    updates = []
    for row in rows:
        values = {
            key: value for key, value in row.items()
            if key in model_columns and key not in {"integrity_hash", "created_at", "updated_at"}
        }
        audit = AuditLog(**values)
        updates.append({"digest": audit.compute_integrity_hash(), "id": row["id"]})
    if updates:
        bind.execute(
            sa.text("UPDATE audit_logs SET integrity_hash = :digest WHERE id = :id"),
            updates,
        )

    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_audit_log_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_logs are append-only';
            END;
            $$ LANGUAGE plpgsql;
        """)
        op.execute("""
            CREATE TRIGGER audit_logs_append_only
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
            BEGIN SELECT RAISE(ABORT, 'audit_logs are append-only'); END;
        """)
        op.execute("""
            CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
            BEGIN SELECT RAISE(ABORT, 'audit_logs are append-only'); END;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update")
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_delete")
    op.drop_index("ix_audit_logs_integrity_hash", table_name="audit_logs")
    op.drop_column("audit_logs", "integrity_hash")
