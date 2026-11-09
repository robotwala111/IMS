"""
Notification Model

Defines notification records for alerts and messages.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(str, enum.Enum):
    """Types of notifications."""
    
    LOW_STOCK = "low_stock"
    EXPIRY_ALERT = "expiry_alert"
    CALIBRATION_DUE = "calibration_due"
    MAINTENANCE_DUE = "maintenance_due"
    TRANSFER_REQUEST = "transfer_request"
    TRANSFER_APPROVED = "transfer_approved"
    TRANSFER_REJECTED = "transfer_rejected"
    TRANSFER_SHIPPED = "transfer_shipped"
    TRANSFER_RECEIVED = "transfer_received"
    RETURN_DATE_DUE = "return_date_due"
    SYSTEM_ALERT = "system_alert"
    USER_MENTION = "user_mention"


class NotificationChannel(str, enum.Enum):
    """Notification delivery channels."""
    
    EMAIL = "email"
    IN_APP = "in_app"
    SLACK = "slack"
    MS_TEAMS = "ms_teams"


class NotificationStatus(str, enum.Enum):
    """Status of notification delivery."""
    
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    READ = "read"


class Notification(Base):
    """Notification record."""
    
    __tablename__ = "notifications"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    
    # Type and channel
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType),
        nullable=False,
        index=True,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel),
        nullable=False,
    )
    
    # Recipient
    recipient_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Content
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Payload (JSON) - additional data for the notification
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Status and timing
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus),
        default=NotificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False)
    dedup_key: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )
    
    # Reference
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        notification_type = self.__dict__.get("notification_type", "<unloaded>")
        status = self.__dict__.get("status", "<unloaded>")
        return f"<Notification(id={id_}, type={notification_type}, status={status})>"
