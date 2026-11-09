"""
Notification Schemas

Pydantic schemas for notifications.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel


class NotificationBase(BaseModel):
    """Base notification attributes."""
    notification_type: str  # low_stock, calibration_due, transfer_pending, etc.
    subject: str
    body: str
    payload: Optional[str] = None


class NotificationResponse(BaseModel):
    """Notification response schema."""
    id: str
    notification_type: str
    channel: str
    subject: str
    body: str
    payload: Optional[str] = None
    status: str
    read_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Paginated notification list response."""
    items: List[NotificationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class NotificationMarkReadRequest(BaseModel):
    """Request to mark multiple notifications as read."""
    notification_ids: List[str]
