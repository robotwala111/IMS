"""
Audit Log Model

Defines audit trail for all system changes.
"""

from datetime import datetime, timezone
from typing import Optional

import hashlib
import hmac
import json

from sqlalchemy import DateTime, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Audit log entry for tracking changes."""
    
    __tablename__ = "audit_logs"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    
    # Request context
    correlation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    
    # Actor
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    user_role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Action details
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    resource_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # HTTP context
    http_method: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    http_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Client info
    client_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Change details
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    changes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # JSON diff
    
    # Result
    status: Mapped[str] = mapped_column(String(20), default="success", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    integrity_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    
    # Additional context
    extra_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    
    # Timestamp
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        action = self.__dict__.get("action", "<unloaded>")
        resource_type = self.__dict__.get("resource_type", "<unloaded>")
        return f"<AuditLog(id={id_}, action={action}, resource={resource_type})>"

    def integrity_payload(self) -> str:
        occurred_at = self.occurred_at
        if isinstance(occurred_at, datetime) and occurred_at.tzinfo is not None:
            occurred_at = occurred_at.astimezone(timezone.utc).replace(tzinfo=None)
        fields = {
            "id": self.id, "correlation_id": self.correlation_id,
            "user_id": self.user_id, "user_email": self.user_email,
            "user_name": self.user_name, "user_role": self.user_role,
            "action": self.action, "resource_type": self.resource_type,
            "resource_id": self.resource_id, "resource_name": self.resource_name,
            "http_method": self.http_method, "http_path": self.http_path,
            "client_ip": self.client_ip, "user_agent": self.user_agent,
            "old_value": self.old_value, "new_value": self.new_value,
            "changes": self.changes, "status": self.status,
            "error_message": self.error_message, "extra_data": self.extra_data,
            "occurred_at": (
                occurred_at.isoformat()
                if occurred_at and hasattr(occurred_at, "isoformat")
                else str(occurred_at) if occurred_at else None
            ),
        }
        return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)

    def compute_integrity_hash(self) -> str:
        from app.core.config import settings
        signing_key = settings.AUDIT_INTEGRITY_KEY or settings.JWT_SECRET_KEY
        return hmac.new(
            signing_key.encode("utf-8"), self.integrity_payload().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def has_valid_integrity_hash(self) -> bool:
        return bool(self.integrity_hash) and hmac.compare_digest(
            self.integrity_hash, self.compute_integrity_hash()
        )


@event.listens_for(AuditLog, "before_insert")
def _sign_audit_log(_mapper, _connection, target: AuditLog) -> None:
    target.integrity_hash = target.compute_integrity_hash()


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _prevent_audit_mutation(_mapper, _connection, _target: AuditLog) -> None:
    raise ValueError("Audit logs are append-only and cannot be modified or deleted")
