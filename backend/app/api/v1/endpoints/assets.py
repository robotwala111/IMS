"""
Serialized Asset Endpoints

CRUD operations for serialized/tracked assets.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_manager_or_admin,
    require_admin,
)
from app.core.exceptions import NotFoundError, ConflictError, BadRequestError
from app.core.logging import get_logger
from app.models.asset import AssetStatus, CalibrationStatus, SerializedAsset
from app.models.calibration import CalibrationRecord
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.schemas.common import MessageResponse
from app.schemas.asset import (
    AssetCreate,
    SerializedProductCreate,
    AssetUpdate,
    AssetResponse,
    AssetListResponse,
    AssetSearchParams,
)
from app.services.asset_service import AssetService
from app.services.audit_service import AuditService
from app.services.permanent_delete_service import PermanentDeleteService
from app.services.item_service import ItemService

logger = get_logger(__name__)
router = APIRouter()


def _inventory_type_key(value: Optional[str]) -> str:
    key = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return {"equipments": "equipment", "instruments": "instrument"}.get(key, key)


@router.get("", response_model=AssetListResponse)
async def list_assets(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    status: Optional[AssetStatus] = Query(None),
    calibration_status: Optional[CalibrationStatus] = Query(None),
    assigned_to_user_id: Optional[str] = Query(None),
    serial_number: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> AssetListResponse:
    """
    List assets with filtering.
    """
    asset_service = AssetService(db)
    
    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    search_params = AssetSearchParams(
        item_id=item_id,
        location_id=location_id,
        status=status,
        calibration_status=calibration_status,
        assigned_to_user_id=assigned_to_user_id,
        serial_number=serial_number,
        search=search,
    )
    
    assets, total = await asset_service.list_assets(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        filters=search_params,
        location_ids=location_ids,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return AssetListResponse(
        items=assets,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: str,
    current_user: CurrentUser,
    db: DB,
) -> AssetResponse:
    """
    Get a specific asset by ID.
    """
    asset_service = AssetService(db)
    asset = await asset_service.get_by_id(asset_id)
    
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    return asset


@router.get("/serial/{serial_number}", response_model=AssetResponse)
async def get_asset_by_serial(
    serial_number: str,
    current_user: CurrentUser,
    db: DB,
) -> AssetResponse:
    """
    Get a specific asset by serial number.
    """
    asset_service = AssetService(db)
    asset = await asset_service.get_by_serial_number(serial_number)
    
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=serial_number)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=serial_number)
    
    return asset


@router.post("", response_model=AssetResponse, status_code=201)
async def create_asset(
    request: AssetCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> AssetResponse:
    """
    Create a new asset (Manager or Admin).
    """
    # Check location access
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    asset_service = AssetService(db)
    audit_service = AuditService(db)
    item_service = ItemService(db)

    item = await item_service.get_by_id(request.item_id)
    if not item:
        raise NotFoundError(resource="Item", resource_id=request.item_id)
    item_type = (item.asset_type or item.category_type_key or "").lower()
    if not item.is_serialized or item.stock_behavior != "serialized" or item_type not in {"equipment", "instrument"}:
        raise BadRequestError(
            message="Products can only be created for serialized Equipment or Instrument items."
        )
    
    # Check for existing serial number
    existing = await asset_service.get_by_serial_number(request.serial_number)
    if existing:
        raise ConflictError(message=f"Asset with serial number {request.serial_number} already exists")
    
    # Create asset
    asset = await asset_service.create(**request.model_dump())
    
    # Audit log
    await audit_service.log_action(
        action="create",
        resource_type="asset",
        resource_id=asset.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"serial_number": asset.serial_number, "location_id": asset.location_id},
    )
    
    asset = await asset_service.get_by_id(asset.id)
    return asset


@router.post("/products", response_model=AssetResponse, status_code=201)
async def create_serialized_product(
    request: SerializedProductCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> AssetResponse:
    """Atomically create an Equipment/Instrument item and serialized asset."""
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)

    category = (
        await db.execute(
            select(Category)
            .options(selectinload(Category.category_type))
            .where(Category.id == request.category_id)
        )
    ).scalar_one_or_none()
    if not category:
        raise NotFoundError(resource="Category", resource_id=request.category_id)

    product_type = _inventory_type_key(category.category_type_key or category.name)
    if (category.stock_behavior or "").lower() != "serialized" or product_type not in {
        "equipment",
        "instrument",
    }:
        raise BadRequestError(
            message="Products can only use serialized Equipment or Instrument categories."
        )

    if not await db.get(Location, request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)

    serial_number = request.serial_number.strip()
    sku = serial_number.upper()
    existing_asset = (
        await db.execute(
            select(SerializedAsset.id).where(
                SerializedAsset.serial_number == serial_number
            )
        )
    ).scalar_one_or_none()
    if existing_asset:
        raise ConflictError(message=f"Product with serial number {serial_number} already exists")

    existing_item = (
        await db.execute(select(Item).where(func.upper(Item.sku) == sku))
    ).scalar_one_or_none()
    item = existing_item
    if item:
        asset_count = (
            await db.execute(
                select(func.count(SerializedAsset.id)).where(
                    SerializedAsset.item_id == item.id
                )
            )
        ).scalar_one()
        if asset_count:
            raise ConflictError(
                message=f"Product with serial number {serial_number} already exists"
            )
        if not item.is_serialized:
            raise ConflictError(message=f"SKU {sku} is already used by a stock item")

        # Recover a partial product left by the previous two-request workflow.
        item.name = request.name
        item.description = request.description
        item.category_id = request.category_id
        item.asset_type = product_type
        item.id_number = request.id_number
        item.manufacturer = request.manufacturer
        item.model = request.model
        item.requires_calibration = product_type == "instrument"
        item.is_active = True
    else:
        item = Item(
            id=AssetService(db).generate_id(),
            id_number=request.id_number,
            sku=sku,
            name=request.name,
            description=request.description,
            category_id=request.category_id,
            asset_type=product_type,
            unit_of_measure="EA",
            manufacturer=request.manufacturer,
            model=request.model,
            is_serialized=True,
            requires_calibration=product_type == "instrument",
            is_active=True,
        )
        db.add(item)
        await db.flush()

    asset_service = AssetService(db)
    asset = SerializedAsset(
        id=asset_service.generate_id(),
        item_id=item.id,
        serial_number=serial_number,
        location_id=request.location_id,
        acquired_at=request.acquired_at,
        supplier_name=request.supplier_name,
        invoice_number=request.invoice_number,
        purchase_order=request.purchase_order,
        cost=request.cost,
        asset_tag=request.id_number,
        notes=request.description,
        status=AssetStatus.IN_SERVICE,
    )
    db.add(asset)
    await db.flush()

    if request.calibration:
        calibration = request.calibration
        existing_certificate = (
            await db.execute(
                select(CalibrationRecord.id).where(
                    CalibrationRecord.certificate_number
                    == calibration.certificate_number
                )
            )
        ).scalar_one_or_none()
        if existing_certificate:
            await db.rollback()
            raise ConflictError(
                message=f"Certificate number {calibration.certificate_number} already exists"
            )
        db.add(
            CalibrationRecord(
                id=asset_service.generate_id(),
                asset_id=asset.id,
                recorded_by_id=current_user.id,
                **calibration.model_dump(),
            )
        )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            message="The product serial number, SKU, or calibration certificate already exists"
        ) from exc

    try:
        await AuditService(db).log_action(
            action="create",
            resource_type="asset",
            resource_id=asset.id,
            user_id=current_user.id,
            old_value=None,
            new_value={
                "serial_number": serial_number,
                "item_id": item.id,
                "location_id": request.location_id,
                "recovered_partial_item": existing_item is not None,
            },
        )
    except Exception as exc:
        await db.rollback()
        logger.warning("Product %s was created but audit logging failed: %s", asset.id, exc)
    return await asset_service.get_by_id(asset.id)


@router.patch("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: str,
    request: AssetUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> AssetResponse:
    """
    Update an asset (Manager or Admin).
    """
    asset_service = AssetService(db)
    audit_service = AuditService(db)
    
    # Get existing asset
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # If changing location, check access to new location
    if request.location_id and request.location_id != asset.location_id:
        if not current_user.has_location_access(request.location_id):
            raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    old_value = {
        "serial_number": asset.serial_number,
        "status": asset.status.value,
        "location_id": asset.location_id,
        "assigned_to_user_id": asset.assigned_to_user_id,
    }
    
    # Update asset
    update_data = request.model_dump(exclude_unset=True)
    if update_data:
        asset = await asset_service.update_asset(asset_id, **update_data)
    
    # Audit log
    new_value = {
        "serial_number": asset.serial_number,
        "status": asset.status.value,
        "location_id": asset.location_id,
        "assigned_to_user_id": asset.assigned_to_user_id,
    }
    await audit_service.log_action(
        action="update",
        resource_type="asset",
        resource_id=asset.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=new_value,
    )
    
    asset = await asset_service.get_by_id(asset.id)
    return asset


@router.patch("/{asset_id}/assign", response_model=AssetResponse)
async def assign_asset(
    asset_id: str,
    user_id: Optional[str] = Query(None, description="User ID to assign to, or null to unassign"),
    current_user: CurrentUser = None,
    db: DB = None,
    _: None = Depends(require_manager_or_admin),
) -> AssetResponse:
    """
    Assign or unassign an asset to/from a user.
    """
    asset_service = AssetService(db)
    audit_service = AuditService(db)
    
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    old_assigned = asset.assigned_to_user_id
    
    updated_asset = await asset_service.update(asset_id, assigned_to_user_id=user_id)
    
    # Audit log
    await audit_service.log_action(
        action="assign" if user_id else "unassign",
        resource_type="asset",
        resource_id=asset.id,
        user_id=current_user.id,
        old_value={"assigned_to_user_id": old_assigned},
        new_value={"assigned_to_user_id": user_id},
    )
    
    updated_asset = await asset_service.get_by_id(updated_asset.id)
    return updated_asset


@router.patch("/{asset_id}/status", response_model=AssetResponse)
async def update_asset_status(
    asset_id: str,
    status: AssetStatus,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> AssetResponse:
    """
    Update asset status (Manager or Admin).
    """
    asset_service = AssetService(db)
    audit_service = AuditService(db)
    
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    old_status = asset.status.value
    
    updated_asset = await asset_service.update_asset(asset_id, status=status)
    
    # Audit log
    await audit_service.log_action(
        action="status_change",
        resource_type="asset",
        resource_id=asset.id,
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": status.value},
    )
    
    updated_asset = await asset_service.get_by_id(updated_asset.id)
    return updated_asset


@router.delete("/{asset_id}", response_model=MessageResponse)
async def deactivate_asset(
    asset_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """Retire a serialized product within the caller's location scope."""
    asset_service = AssetService(db)
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    old_status = asset.status.value
    await asset_service.delete_asset(asset_id)
    await AuditService(db).log_action(
        action="deactivate",
        resource_type="asset",
        resource_id=asset_id,
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": "retired"},
    )
    return MessageResponse(message="Product deactivated")


@router.delete("/{asset_id}/permanent", response_model=MessageResponse)
async def permanently_delete_asset(
    asset_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete an unreferenced serialized product (Admin only)."""
    name = await PermanentDeleteService(db).delete("asset", asset_id, current_user)
    return MessageResponse(message=f"Product {name} permanently deleted")
