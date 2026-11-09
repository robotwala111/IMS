"""
Maintenance Endpoints

Maintenance record management for serialized assets.
"""

from typing import Optional
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_manager_or_admin,
    require_admin,
    require_location_access,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.asset import (
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    MaintenanceRecordListResponse,
)
from app.services.maintenance_service import MaintenanceService
from app.services.asset_service import AssetService
from app.services.audit_service import AuditService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/records", response_model=MaintenanceRecordListResponse)
async def list_maintenance_records(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    asset_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    maintenance_type: Optional[str] = Query(None),
    due_before: Optional[date] = Query(None),
) -> MaintenanceRecordListResponse:
    """
    List maintenance records with filtering.
    """
    maintenance_service = MaintenanceService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    records, total = await maintenance_service.list_records(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "scheduled_at",
        sort_order=pagination["sort_order"] or "desc",
        asset_id=asset_id,
        location_id=location_id,
        maintenance_type=maintenance_type,
        due_before=due_before,
        location_ids=location_ids,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return MaintenanceRecordListResponse(
        items=records,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/due-soon", response_model=MaintenanceRecordListResponse)
async def get_maintenance_due_soon(
    current_user: CurrentUser,
    db: DB,
    days: int = Query(30, ge=1, le=365),
) -> MaintenanceRecordListResponse:
    """
    Get scheduled maintenance due within the specified number of days.
    """
    maintenance_service = MaintenanceService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    records = await maintenance_service.get_due_soon(
        days=days,
        location_ids=location_ids,
    )
    
    return MaintenanceRecordListResponse(
        items=records,
        total=len(records),
        page=1,
        page_size=len(records),
        pages=1,
    )


@router.get("/records/{record_id}", response_model=MaintenanceRecordResponse)
async def get_maintenance_record(
    record_id: str,
    current_user: CurrentUser,
    db: DB,
) -> MaintenanceRecordResponse:
    """
    Get a specific maintenance record by ID.
    """
    maintenance_service = MaintenanceService(db)
    record = await maintenance_service.get_by_id(record_id)
    
    if not record:
        raise NotFoundError(resource="Maintenance Record", resource_id=record_id)
    asset_service = AssetService(db)
    asset = await asset_service.get_by_id(record.asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=record.asset_id)
    require_location_access(current_user, asset.location_id)

    return record


@router.post("/assets/{asset_id}/records", response_model=MaintenanceRecordResponse, status_code=201)
async def create_maintenance_record(
    asset_id: str,
    request: MaintenanceRecordCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MaintenanceRecordResponse:
    """
    Create a new maintenance record for an asset.
    """
    asset_service = AssetService(db)
    maintenance_service = MaintenanceService(db)
    audit_service = AuditService(db)
    
    # Get asset
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Create record
    record = await maintenance_service.create(
        asset_id=asset_id,
        performed_by_id=current_user.id,
        **request.model_dump(),
    )
    
    # Audit log
    await audit_service.log_action(
        action="create_maintenance",
        resource_type="maintenance_record",
        resource_id=record.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "asset_id": asset_id,
            "maintenance_type": record.maintenance_type,
            "scheduled_at": str(record.scheduled_at),
        },
    )
    
    record = await maintenance_service.get_by_id(record.id)
    return record


@router.get("/assets/{asset_id}/records", response_model=MaintenanceRecordListResponse)
async def get_asset_maintenance_history(
    asset_id: str,
    current_user: CurrentUser,
    db: DB,
) -> MaintenanceRecordListResponse:
    """
    Get maintenance history for a specific asset.
    """
    asset_service = AssetService(db)
    maintenance_service = MaintenanceService(db)
    
    # Get asset
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    records = await maintenance_service.get_asset_history(asset_id)
    
    return MaintenanceRecordListResponse(
        items=records,
        total=len(records),
        page=1,
        page_size=len(records),
        pages=1,
    )


@router.patch("/records/{record_id}", response_model=MaintenanceRecordResponse)
async def update_maintenance_record(
    record_id: str,
    request: MaintenanceRecordCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MaintenanceRecordResponse:
    """
    Update a maintenance record (Manager or Admin).
    """
    maintenance_service = MaintenanceService(db)
    audit_service = AuditService(db)
    
    record = await maintenance_service.get_by_id(record_id)
    if not record:
        raise NotFoundError(resource="Maintenance Record", resource_id=record_id)
    asset_service = AssetService(db)
    asset = await asset_service.get_by_id(record.asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=record.asset_id)
    require_location_access(current_user, asset.location_id)
    
    old_data = {
        "maintenance_type": record.maintenance_type,
        "description": record.description,
        "labor_cost": str(record.labor_cost) if record.labor_cost else None,
        "parts_cost": str(record.parts_cost) if record.parts_cost else None,
    }
    
    updated = await maintenance_service.update(record_id, **request.model_dump())
    
    # Audit log
    await audit_service.log_action(
        action="update_maintenance",
        resource_type="maintenance_record",
        resource_id=record_id,
        user_id=current_user.id,
        old_value=old_data,
        new_value=request.model_dump(),
    )
    
    updated = await maintenance_service.get_by_id(updated.id)
    return updated


@router.delete("/records/{record_id}", response_model=MessageResponse)
async def delete_maintenance_record(
    record_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    """
    Delete a maintenance record (Manager or Admin).
    """
    maintenance_service = MaintenanceService(db)
    audit_service = AuditService(db)
    
    record = await maintenance_service.get_by_id(record_id)
    if not record:
        raise NotFoundError(resource="Maintenance Record", resource_id=record_id)
    asset_service = AssetService(db)
    asset = await asset_service.get_by_id(record.asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=record.asset_id)
    require_location_access(current_user, asset.location_id)
    
    old_data = {
        "asset_id": record.asset_id,
        "maintenance_type": record.maintenance_type,
        "scheduled_at": str(record.scheduled_at),
    }
    
    await maintenance_service.delete(record_id)
    
    # Audit log
    await audit_service.log_action(
        action="delete_maintenance",
        resource_type="maintenance_record",
        resource_id=record_id,
        user_id=current_user.id,
        old_value=old_data,
        new_value=None,
    )
    
    return MessageResponse(message="Maintenance record deleted successfully")
