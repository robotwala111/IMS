"""
Audit Log Endpoints

Audit log viewing for administrators.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import CurrentUser, DB, PaginationParams, require_admin_or_ho_manager
from app.core.logging import get_logger
from app.schemas.audit import (
    AuditLogResponse,
    AuditLogListResponse,
)
from app.services.audit_service import AuditService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/integrity")
async def verify_audit_integrity(
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> dict:
    """Verify every retained audit record against its integrity signature."""
    return await AuditService(db).verify_integrity()


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    action: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    important_only: bool = Query(True, description="Show only important transactions, excluding routine actions like logins and minor updates"),
    _: None = Depends(require_admin_or_ho_manager),
) -> AuditLogListResponse:
    """
    List audit logs with filtering (Admin only).
    """
    audit_service = AuditService(db)
    
    logs, total = await audit_service.list_logs(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "occurred_at",
        sort_order=pagination["sort_order"] or "desc",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
        important_only=important_only,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return AuditLogListResponse(
        items=logs,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/actions")
async def list_action_types(
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> dict:
    """
    List all audit action types (Admin only).
    """
    audit_service = AuditService(db)
    actions = await audit_service.get_action_types()
    
    return {"actions": actions}


@router.get("/resource-types")
async def list_resource_types(
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> dict:
    """
    List all resource types (Admin only).
    """
    audit_service = AuditService(db)
    resource_types = await audit_service.get_resource_types()
    
    return {"resource_types": resource_types}


@router.get("/user/{user_id}", response_model=AuditLogListResponse)
async def get_user_activity(
    user_id: str,
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    _: None = Depends(require_admin_or_ho_manager),
) -> AuditLogListResponse:
    """
    Get audit logs for a specific user (Admin only).
    """
    audit_service = AuditService(db)
    
    logs, total = await audit_service.list_logs(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "occurred_at",
        sort_order=pagination["sort_order"] or "desc",
        user_id=user_id,
        start_date=start_date,
        end_date=end_date,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return AuditLogListResponse(
        items=logs,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/resource/{resource_type}/{resource_id}", response_model=AuditLogListResponse)
async def get_resource_history(
    resource_type: str,
    resource_id: str,
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    _: None = Depends(require_admin_or_ho_manager),
) -> AuditLogListResponse:
    """
    Get audit history for a specific resource (Admin only).
    """
    audit_service = AuditService(db)
    
    logs, total = await audit_service.list_logs(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "occurred_at",
        sort_order=pagination["sort_order"] or "desc",
        resource_type=resource_type,
        resource_id=resource_id,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return AuditLogListResponse(
        items=logs,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )
