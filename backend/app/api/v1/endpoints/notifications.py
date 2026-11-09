"""
Notifications Endpoints

User notification management.
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import CurrentUser, DB, PaginationParams
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    NotificationMarkReadRequest,
)
from app.services.notification_service import NotificationService

logger = get_logger(__name__)
router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    unread_only: bool = Query(False),
    notification_type: Optional[str] = Query(None),
) -> NotificationListResponse:
    """
    List notifications for current user.
    """
    notification_service = NotificationService(db)
    
    notifications, total = await notification_service.list_for_user(
        user_id=current_user.id,
        page=pagination["page"],
        page_size=pagination["page_size"],
        unread_only=unread_only,
        notification_type=notification_type,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return NotificationListResponse(
        items=notifications,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/unread-count")
async def get_unread_count(
    current_user: CurrentUser,
    db: DB,
) -> dict:
    """
    Get count of unread notifications.
    """
    notification_service = NotificationService(db)
    count = await notification_service.get_unread_count(current_user.id)
    
    return {"unread_count": count}


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: str,
    current_user: CurrentUser,
    db: DB,
) -> NotificationResponse:
    """
    Get a specific notification.
    """
    notification_service = NotificationService(db)
    notification = await notification_service.get_by_id(notification_id)
    
    if not notification:
        raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    # Only owner can view their notifications
    if notification.recipient_id != current_user.id:
        raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    return notification


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_as_read(
    notification_id: str,
    current_user: CurrentUser,
    db: DB,
) -> NotificationResponse:
    """
    Mark a notification as read.
    """
    notification_service = NotificationService(db)
    notification = await notification_service.get_by_id(notification_id)
    
    if not notification:
        raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    # Only owner can mark their notifications
    if notification.recipient_id != current_user.id:
        raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    updated = await notification_service.mark_as_read(notification_id)
    
    return updated


@router.patch("/mark-all-read", response_model=MessageResponse)
async def mark_all_as_read(
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Mark all notifications as read.
    """
    notification_service = NotificationService(db)
    count = await notification_service.mark_all_as_read(current_user.id)
    
    return MessageResponse(message=f"Marked {count} notifications as read")


@router.post("/mark-read", response_model=MessageResponse)
async def mark_multiple_as_read(
    request: NotificationMarkReadRequest,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Mark multiple notifications as read.
    """
    notification_service = NotificationService(db)
    
    # Verify ownership of all notifications
    for notification_id in request.notification_ids:
        notification = await notification_service.get_by_id(notification_id)
        if not notification or notification.recipient_id != current_user.id:
            raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    count = await notification_service.mark_multiple_as_read(request.notification_ids)
    
    return MessageResponse(message=f"Marked {count} notifications as read")


@router.delete("/{notification_id}", response_model=MessageResponse)
async def delete_notification(
    notification_id: str,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Delete a notification.
    """
    notification_service = NotificationService(db)
    notification = await notification_service.get_by_id(notification_id)
    
    if not notification:
        raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    # Only owner can delete their notifications
    if notification.recipient_id != current_user.id:
        raise NotFoundError(resource="Notification", resource_id=notification_id)
    
    await notification_service.delete(notification_id)
    
    return MessageResponse(message="Notification deleted successfully")


@router.delete("", response_model=MessageResponse)
async def delete_all_read_notifications(
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Delete all read notifications.
    """
    notification_service = NotificationService(db)
    count = await notification_service.delete_all_read(current_user.id)
    
    return MessageResponse(message=f"Deleted {count} read notifications")
