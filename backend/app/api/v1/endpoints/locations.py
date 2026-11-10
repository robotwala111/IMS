"""
Location Management Endpoints

CRUD operations for inventory locations.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_admin,
    require_admin_or_ho_manager,
    require_manager_or_admin,
)
from app.core.exceptions import AuthorizationError, NotFoundError, ConflictError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.location import (
    LocationCreate,
    LocationUpdate,
    LocationResponse,
    LocationListResponse,
    LocationSummary,
)
from app.services.location_service import LocationService
from app.services.audit_service import AuditService
from app.services.permanent_delete_service import PermanentDeleteService

logger = get_logger(__name__)
router = APIRouter()


@router.get("", response_model=LocationListResponse)
async def list_locations(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
) -> LocationListResponse:
    """
    List locations.
    
    Non-admin users only see their assigned locations.
    """
    location_service = LocationService(db)
    
    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    locations, total = await location_service.list_locations(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        is_active=is_active,
        search=search,
        location_ids=location_ids,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return LocationListResponse(
        items=[LocationResponse.model_validate(loc) for loc in locations],
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/summary", response_model=List[LocationSummary])
async def get_location_summary(
    current_user: CurrentUser,
    db: DB,
) -> List[LocationSummary]:
    """
    Get a brief list of locations for dropdowns.
    """
    location_service = LocationService(db)
    
    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    locations = await location_service.get_active_locations(location_ids=location_ids)
    
    return [LocationSummary.model_validate(loc) for loc in locations]


@router.get("/transfer-destinations", response_model=List[LocationSummary])
async def get_transfer_destination_locations(
    current_user: CurrentUser,
    db: DB,
) -> List[LocationSummary]:
    """
    Get valid active destination locations for a transfer request.

    A Location Manager requests stock for their own assigned location, while
    company-wide managers may choose any active destination.
    """
    location_service = LocationService(db)
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    locations = await location_service.get_active_locations(location_ids=location_ids)
    return [LocationSummary.model_validate(loc) for loc in locations]


@router.get("/transfer-sources", response_model=List[LocationSummary])
async def get_transfer_source_locations(
    current_user: CurrentUser,
    db: DB,
) -> List[LocationSummary]:
    """Get all active supplying locations available to transfer requesters."""
    location_service = LocationService(db)
    locations = await location_service.get_active_locations(location_ids=None)
    return [LocationSummary.model_validate(loc) for loc in locations]


@router.get("/{location_id}", response_model=LocationResponse)
async def get_location(
    location_id: str,
    current_user: CurrentUser,
    db: DB,
) -> LocationResponse:
    """
    Get a specific location by ID.
    """
    # Check access
    if not current_user.has_location_access(location_id):
        raise NotFoundError(resource="Location", resource_id=location_id)
    
    location_service = LocationService(db)
    location = await location_service.get_by_id(location_id)
    
    if not location:
        raise NotFoundError(resource="Location", resource_id=location_id)
    
    return LocationResponse.model_validate(location)


@router.post("", response_model=LocationResponse, status_code=201)
async def create_location(
    request: LocationCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> LocationResponse:
    """
    Create a new location (Admin only).
    """
    location_service = LocationService(db)
    audit_service = AuditService(db)
    
    # Check for existing code
    existing = await location_service.get_by_code(request.code)
    if existing:
        raise ConflictError(message=f"Location with code {request.code} already exists")
    
    # Create location
    location = await location_service.create(**request.model_dump())
    
    # Audit log
    await audit_service.log_action(
        action="create",
        resource_type="location",
        resource_id=location.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"code": location.code, "name": location.name},
    )
    
    location = await location_service.get_by_id(location.id)
    return LocationResponse.model_validate(location)


@router.patch("/{location_id}", response_model=LocationResponse)
async def update_location(
    location_id: str,
    request: LocationUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> LocationResponse:
    """
    Update a location (Admin only).
    """
    location_service = LocationService(db)
    audit_service = AuditService(db)
    
    # Get existing location
    location = await location_service.get_by_id(location_id)
    if not location:
        raise NotFoundError(resource="Location", resource_id=location_id)
    
    old_value = {"code": location.code, "name": location.name, "is_active": location.is_active}
    
    # Check code uniqueness if changing
    if request.code and request.code != location.code:
        existing = await location_service.get_by_code(request.code)
        if existing:
            raise ConflictError(message=f"Location with code {request.code} already exists")
    
    # Update location
    update_data = request.model_dump(exclude_unset=True)
    if location.is_active and update_data.get("is_active") is False:
        blockers = await location_service.get_deactivation_blockers(location_id)
        if blockers:
            raise ConflictError(
                message="Cannot deactivate location with " + ", ".join(blockers) + "."
            )
    if update_data:
        location = await location_service.update(location_id, **update_data)
    
    # Audit log
    new_value = {"code": location.code, "name": location.name, "is_active": location.is_active}
    await audit_service.log_action(
        action="update",
        resource_type="location",
        resource_id=location.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=new_value,
    )
    
    location = await location_service.get_by_id(location.id)
    return LocationResponse.model_validate(location)


@router.delete("/{location_id}", response_model=MessageResponse)
async def delete_location(
    location_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Deactivate a location within the manager's location scope.
    """
    location_service = LocationService(db)
    audit_service = AuditService(db)
    
    location = await location_service.get_by_id(location_id)
    if not location:
        raise NotFoundError(resource="Location", resource_id=location_id)
    if not current_user.has_location_access(location_id):
        raise AuthorizationError(message="You do not have access to this location")
    
    blockers = await location_service.get_deactivation_blockers(location_id)
    if blockers:
        raise ConflictError(
            message="Cannot deactivate location with " + ", ".join(blockers) + "."
        )
    
    # Deactivate
    await location_service.update(location_id, is_active=False)
    
    # Audit log
    await audit_service.log_action(
        action="deactivate",
        resource_type="location",
        resource_id=location.id,
        user_id=current_user.id,
        old_value={"is_active": True},
        new_value={"is_active": False},
    )
    
    return MessageResponse(message=f"Location {location.code} has been deactivated")


@router.delete("/{location_id}/permanent", response_model=MessageResponse)
async def permanently_delete_location(
    location_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete an unreferenced location (Admin only)."""
    name = await PermanentDeleteService(db).delete("location", location_id, current_user)
    return MessageResponse(message=f"Location {name} permanently deleted")
