"""
Audit Log Schemas

Pydantic schemas for audit logging.
"""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, model_validator


class AuditLogResponse(BaseModel):
    """Audit log entry response schema."""
    id: str
    correlation_id: Optional[str] = None
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    resource_name: Optional[str] = None
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    changes: Optional[Any] = None
    integrity_hash: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            value = {
                "id": getattr(value, "id", None),
                "correlation_id": getattr(value, "correlation_id", None),
                "action": getattr(value, "action", None),
                "resource_type": getattr(value, "resource_type", None),
                "resource_id": getattr(value, "resource_id", None),
                "resource_name": getattr(value, "resource_name", None),
                "user_id": getattr(value, "user_id", None),
                "user_email": getattr(value, "user_email", None),
                "user_name": getattr(value, "user_name", None),
                "old_value": getattr(value, "old_value", None),
                "new_value": getattr(value, "new_value", None),
                "ip_address": getattr(value, "client_ip", None),
                "user_agent": getattr(value, "user_agent", None),
                "status": getattr(value, "status", None),
                "error_message": getattr(value, "error_message", None),
                "changes": getattr(value, "changes", None),
                "integrity_hash": getattr(value, "integrity_hash", None),
                "created_at": getattr(value, "occurred_at", None) or getattr(value, "created_at", None),
            }

        for key in ("old_value", "new_value", "changes"):
            raw = value.get(key)
            if isinstance(raw, str):
                try:
                    value[key] = json.loads(raw)
                except Exception:
                    value[key] = raw

        if value.get("ip_address") is None and value.get("client_ip") is not None:
            value["ip_address"] = value.get("client_ip")

        if value.get("created_at") is None and value.get("occurred_at") is not None:
            value["created_at"] = value.get("occurred_at")

        return value


class AuditLogListResponse(BaseModel):
    """Paginated audit log list response."""
    items: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    pages: int
