"""
Notification Service

Handles user notification management.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.notification import Notification, NotificationStatus, NotificationType, NotificationChannel
from app.models.audit import AuditLog
from app.services.base_service import BaseService


class NotificationService(BaseService[Notification]):
    """Service for notification management."""
    
    @property
    def model(self):
        return Notification
    
    async def list_for_user(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        unread_only: bool = False,
        notification_type: Optional[str] = None,
    ) -> Tuple[List[Notification], int]:
        """
        List notifications for a user.
        
        Returns:
            Tuple of (notifications, total_count)
        """
        query = select(Notification).where(Notification.recipient_id == user_id)
        
        if unread_only:
            query = query.where(Notification.status != NotificationStatus.READ)
        
        if notification_type:
            query = query.where(Notification.notification_type == notification_type)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting and pagination
        query = query.order_by(Notification.created_at.desc())
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        notifications = list(result.scalars().all())
        
        return notifications, total
    
    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications for a user."""
        result = await self.db.execute(
            select(func.count(Notification.id)).where(
                and_(
                    Notification.recipient_id == user_id,
                    Notification.status != NotificationStatus.READ,
                )
            )
        )
        return result.scalar_one()
    
    async def mark_as_read(self, notification_id: str) -> Notification:
        """Mark a notification as read."""
        notification = await self.get_by_id(notification_id)
        if not notification:
            raise NotFoundError(resource="Notification", resource_id=notification_id)
        
        notification.status = NotificationStatus.READ
        notification.read_at = datetime.now(timezone.utc)
        
        await self.db.commit()
        await self.db.refresh(notification)
        
        return notification
    
    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        result = await self.db.execute(
            update(Notification)
            .where(
                and_(
                    Notification.recipient_id == user_id,
                    Notification.status != NotificationStatus.READ,
                )
            )
            .values(status=NotificationStatus.READ, read_at=datetime.now(timezone.utc))
        )
        
        await self.db.commit()
        return result.rowcount
    
    async def mark_multiple_as_read(self, notification_ids: List[str]) -> int:
        """Mark multiple notifications as read."""
        result = await self.db.execute(
            update(Notification)
            .where(Notification.id.in_(notification_ids))
            .values(status=NotificationStatus.READ, read_at=datetime.now(timezone.utc))
        )
        
        await self.db.commit()
        return result.rowcount
    
    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        """Create a notification for a user."""
        notification = Notification(
            id=self.generate_id(),
            recipient_id=user_id,
            notification_type=notification_type,
            channel=NotificationChannel.IN_APP,
            subject=title,
            body=message,
            payload=json.dumps(data) if data else None,
            status=NotificationStatus.PENDING,
        )
        
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        
        return notification

    async def enqueue_email(
        self,
        *,
        recipient_emails: List[str],
        notification_type: str,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        recipient_id: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        dedup_key: Optional[str] = None,
    ) -> Notification:
        """Persist an email for reliable, retryable delivery."""
        emails = sorted({email.strip().lower() for email in recipient_emails if email.strip()})
        if not emails:
            raise ValueError("At least one recipient email is required")
        if dedup_key:
            existing = await self.db.execute(
                select(Notification).where(Notification.dedup_key == dedup_key)
            )
            notification = existing.scalar_one_or_none()
            if notification:
                return notification
        notification = Notification(
            id=self.generate_id(), notification_type=notification_type,
            channel=NotificationChannel.EMAIL, recipient_id=recipient_id,
            recipient_email=", ".join(emails), subject=subject, body=body_text or body_html,
            payload=json.dumps({"body_html": body_html, "body_text": body_text}),
            status=NotificationStatus.PENDING, scheduled_at=datetime.now(timezone.utc),
            reference_type=reference_type, reference_id=reference_id, dedup_key=dedup_key,
        )
        self.db.add(notification)
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def process_email_outbox(
        self, *, max_items: int = 50, max_retries: int = 5, email_service=None,
    ) -> Dict[str, int]:
        """Claim and deliver due email rows; failed attempts remain durable."""
        if email_service is None:
            from app.services.email_service import get_email_service
            email_service = get_email_service()
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(Notification)
            .where(
                Notification.channel == NotificationChannel.EMAIL,
                Notification.status.in_([NotificationStatus.PENDING, NotificationStatus.FAILED]),
                Notification.retry_count < max_retries,
                or_(Notification.scheduled_at.is_(None), Notification.scheduled_at <= now),
            )
            .order_by(Notification.created_at, Notification.id)
            .limit(max_items)
            .with_for_update(skip_locked=True)
        )
        queued = list(result.scalars().all())
        sent = failed = 0
        for notification in queued:
            payload = json.loads(notification.payload) if notification.payload else {}
            recipients = [
                email.strip() for email in (notification.recipient_email or "").split(",")
                if email.strip()
            ]
            ok = bool(recipients) and email_service.send_email(
                to_emails=recipients, subject=notification.subject,
                body_html=payload.get("body_html") or notification.body,
                body_text=payload.get("body_text") or notification.body,
            )
            notification.retry_count += 1
            if ok:
                notification.status = NotificationStatus.SENT
                notification.sent_at = now
                notification.scheduled_at = None
                notification.error_message = None
                sent += 1
            else:
                notification.status = NotificationStatus.FAILED
                notification.error_message = "Email provider did not accept the message"
                notification.scheduled_at = (
                    now + timedelta(minutes=2 ** notification.retry_count)
                    if notification.retry_count < max_retries else None
                )
                self.db.add(AuditLog(
                    id=self.generate_id(), action="email_delivery_failed",
                    resource_type="notification", resource_id=notification.id,
                    user_id=None, user_email="system@email-outbox", user_role="system",
                    new_value=json.dumps({
                        "subject": notification.subject,
                        "recipient_email": notification.recipient_email,
                        "retry_count": notification.retry_count,
                    }),
                    status="failure", error_message=notification.error_message,
                    occurred_at=now,
                ))
                failed += 1
        await self.db.commit()
        return {"claimed": len(queued), "sent": sent, "failed": failed}
    
    async def create_bulk_notifications(
        self,
        user_ids: List[str],
        notification_type: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> List[Notification]:
        """Create notifications for multiple users."""
        notifications = []
        
        for user_id in user_ids:
            notification = Notification(
                id=self.generate_id(),
                recipient_id=user_id,
                notification_type=notification_type,
                channel=NotificationChannel.IN_APP,
                subject=title,
                body=message,
                payload=json.dumps(data) if data else None,
                status=NotificationStatus.PENDING,
            )
            self.db.add(notification)
            notifications.append(notification)
        
        await self.db.commit()
        return notifications
    
    async def delete(self, notification_id: str) -> bool:
        """Delete a notification."""
        notification = await self.get_by_id(notification_id)
        if not notification:
            raise NotFoundError(resource="Notification", resource_id=notification_id)
        
        await self.db.delete(notification)
        await self.db.commit()
        
        return True
    
    async def delete_all_read(self, user_id: str) -> int:
        """Delete all read notifications for a user."""
        result = await self.db.execute(
            select(Notification).where(
                and_(
                    Notification.recipient_id == user_id,
                    Notification.status == NotificationStatus.READ,
                )
            )
        )
        notifications = result.scalars().all()
        
        count = 0
        for notification in notifications:
            await self.db.delete(notification)
            count += 1
        
        await self.db.commit()
        return count
