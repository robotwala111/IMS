"""
Calibration Endpoints

Calibration record management for serialized assets.
"""

from typing import Optional
from datetime import date
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, UploadFile, File
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_manager_or_admin,
    require_location_access,
)
from app.core.exceptions import NotFoundError, ConflictError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.asset import (
    CalibrationRecordCreate,
    CalibrationRecordResponse,
    CalibrationRecordListResponse,
    CalibrationSupplierTransactionCreate,
    CalibrationSupplierTransactionListResponse,
    CalibrationSupplierTransactionResponse,
)
from app.models.asset import AssetStatus, SerializedAsset
from app.models.calibration import CalibrationSupplierTransaction
from app.services.calibration_service import CalibrationService
from app.services.asset_service import AssetService
from app.services.audit_service import AuditService

logger = get_logger(__name__)
router = APIRouter()


def _supplier_transaction_response(txn: CalibrationSupplierTransaction) -> CalibrationSupplierTransactionResponse:
    asset = txn.asset
    item = asset.item if asset else None
    return CalibrationSupplierTransactionResponse(
        id=txn.id,
        asset_id=txn.asset_id,
        serial_number=asset.serial_number if asset else None,
        instrument_name=item.name if item else None,
        supplier_name=txn.supplier_name,
        sent_at=txn.sent_at,
        received_at=txn.received_at,
        notes=txn.notes,
        recorded_by_id=txn.recorded_by_id,
        created_at=txn.created_at,
        updated_at=txn.updated_at,
    )


@router.get("/records", response_model=CalibrationRecordListResponse)
async def list_calibration_records(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    asset_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    due_before: Optional[date] = Query(None),
    expired_only: bool = Query(False),
) -> CalibrationRecordListResponse:
    """
    List calibration records with filtering.
    """
    calibration_service = CalibrationService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    records, total = await calibration_service.list_records(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "due_at",
        sort_order=pagination["sort_order"] or "asc",
        asset_id=asset_id,
        location_id=location_id,
        due_before=due_before,
        expired_only=expired_only,
        location_ids=location_ids,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return CalibrationRecordListResponse(
        items=records,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/due-soon", response_model=CalibrationRecordListResponse)
async def get_calibrations_due_soon(
    current_user: CurrentUser,
    db: DB,
    days: int = Query(30, ge=1, le=365),
) -> CalibrationRecordListResponse:
    """
    Get calibrations due within the specified number of days.
    """
    calibration_service = CalibrationService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    records = await calibration_service.get_due_soon(
        days=days,
        location_ids=location_ids,
    )
    
    return CalibrationRecordListResponse(
        items=records,
        total=len(records),
        page=1,
        page_size=len(records),
        pages=1,
    )


@router.get("/supplier-transactions", response_model=CalibrationSupplierTransactionListResponse)
async def list_calibration_supplier_transactions(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    asset_id: Optional[str] = Query(None),
) -> CalibrationSupplierTransactionListResponse:
    """List supplier send/receive transactions for instrument calibration."""
    query = (
        select(CalibrationSupplierTransaction)
        .options(
            selectinload(CalibrationSupplierTransaction.asset).selectinload(SerializedAsset.item),
            selectinload(CalibrationSupplierTransaction.asset).selectinload(SerializedAsset.location),
        )
    )
    count_query = select(func.count(CalibrationSupplierTransaction.id))

    if asset_id:
        query = query.where(CalibrationSupplierTransaction.asset_id == asset_id)
        count_query = count_query.where(CalibrationSupplierTransaction.asset_id == asset_id)

    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
        query = query.join(SerializedAsset, SerializedAsset.id == CalibrationSupplierTransaction.asset_id).where(
            SerializedAsset.location_id.in_(location_ids)
        )
        count_query = count_query.join(SerializedAsset, SerializedAsset.id == CalibrationSupplierTransaction.asset_id).where(
            SerializedAsset.location_id.in_(location_ids)
        )

    total = (await db.execute(count_query)).scalar_one()
    query = query.order_by(CalibrationSupplierTransaction.sent_at.desc()).offset(
        (pagination["page"] - 1) * pagination["page_size"]
    ).limit(pagination["page_size"])
    result = await db.execute(query)
    items = [_supplier_transaction_response(txn) for txn in result.scalars().unique().all()]
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    return CalibrationSupplierTransactionListResponse(
        items=items,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.post("/supplier-transactions", response_model=CalibrationSupplierTransactionResponse, status_code=201)
async def create_calibration_supplier_transaction(
    request: CalibrationSupplierTransactionCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> CalibrationSupplierTransactionResponse:
    """Record an instrument sent to or received from a calibration supplier."""
    asset_service = AssetService(db)
    audit_service = AuditService(db)
    asset = await asset_service.get_by_id(request.asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=request.asset_id)
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=request.asset_id)
    if not asset.item or not asset.item.requires_calibration:
        raise ConflictError(message="Supplier calibration is available only for instruments requiring calibration")
    if asset.status in {AssetStatus.RETIRED, AssetStatus.LOST}:
        raise ConflictError(message="Calibration cannot be recorded for a retired or lost instrument")
    if asset.status in {AssetStatus.OUT_OF_SERVICE, AssetStatus.UNDER_MAINTENANCE}:
        raise ConflictError(
            message="Resolve the instrument's current service status before sending it for calibration"
        )

    txn = CalibrationSupplierTransaction(
        id=str(uuid4()),
        asset_id=request.asset_id,
        recorded_by_id=current_user.id,
        sent_at=request.sent_at,
        supplier_name=request.supplier_name,
        received_at=request.received_at,
        notes=request.notes,
    )
    db.add(txn)
    if request.received_at:
        if asset.status == AssetStatus.UNDER_CALIBRATION:
            asset.status = AssetStatus.IN_SERVICE
    else:
        asset.status = AssetStatus.UNDER_CALIBRATION
    await db.commit()
    await db.refresh(txn)

    await audit_service.log_action(
        action="create_calibration_supplier_transaction",
        resource_type="calibration_supplier_transaction",
        resource_id=txn.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "asset_id": txn.asset_id,
            "supplier_name": txn.supplier_name,
            "sent_at": str(txn.sent_at),
            "received_at": str(txn.received_at) if txn.received_at else None,
            "asset_status": asset.status.value,
        },
    )
    result = await db.execute(
        select(CalibrationSupplierTransaction)
        .options(selectinload(CalibrationSupplierTransaction.asset).selectinload(SerializedAsset.item))
        .where(CalibrationSupplierTransaction.id == txn.id)
    )
    return _supplier_transaction_response(result.scalar_one())


@router.get("/expired", response_model=CalibrationRecordListResponse)
async def get_expired_calibrations(
    current_user: CurrentUser,
    db: DB,
) -> CalibrationRecordListResponse:
    """
    Get all assets with expired calibrations.
    """
    calibration_service = CalibrationService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    records = await calibration_service.get_expired(location_ids=location_ids)
    
    return CalibrationRecordListResponse(
        items=records,
        total=len(records),
        page=1,
        page_size=len(records),
        pages=1,
    )


@router.get("/records/{record_id}", response_model=CalibrationRecordResponse)
async def get_calibration_record(
    record_id: str,
    current_user: CurrentUser,
    db: DB,
) -> CalibrationRecordResponse:
    """
    Get a specific calibration record by ID.
    """
    calibration_service = CalibrationService(db)
    record = await calibration_service.get_by_id(record_id)
    
    if not record:
        raise NotFoundError(resource="Calibration Record", resource_id=record_id)
    asset_service = AssetService(db)
    asset = await asset_service.get_by_id(record.asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=record.asset_id)
    require_location_access(current_user, asset.location_id)

    return record


@router.post("/assets/{asset_id}/records", response_model=CalibrationRecordResponse, status_code=201)
async def create_calibration_record(
    asset_id: str,
    request: CalibrationRecordCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> CalibrationRecordResponse:
    """
    Create a new calibration record for an asset (Manager or Admin).
    """
    asset_service = AssetService(db)
    calibration_service = CalibrationService(db)
    audit_service = AuditService(db)
    
    # Get asset
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    if not asset.item or not asset.item.requires_calibration:
        raise ConflictError(message="Calibration records can only be added to instruments requiring calibration")
    if asset.status in {AssetStatus.RETIRED, AssetStatus.LOST}:
        raise ConflictError(message="Calibration cannot be recorded for a retired or lost instrument")
    
    # Check for duplicate certificate number
    existing = await calibration_service.get_by_certificate_number(request.certificate_number)
    if existing:
        raise ConflictError(message=f"Certificate number {request.certificate_number} already exists")
    
    # Create record
    record = await calibration_service.create(
        asset_id=asset_id,
        recorded_by_id=current_user.id,
        **request.model_dump(),
    )
    if record.result == "pass" and asset.status == AssetStatus.UNDER_CALIBRATION:
        asset.status = AssetStatus.IN_SERVICE
        await db.commit()
    
    # Audit log
    await audit_service.log_action(
        action="create_calibration",
        resource_type="calibration_record",
        resource_id=record.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "asset_id": asset_id,
            "certificate_number": record.certificate_number,
            "performed_at": str(record.performed_at),
            "due_at": str(record.due_at),
        },
    )
    
    record = await calibration_service.get_by_id(record.id)
    return record


@router.get("/assets/{asset_id}/records", response_model=CalibrationRecordListResponse)
async def get_asset_calibration_history(
    asset_id: str,
    current_user: CurrentUser,
    db: DB,
) -> CalibrationRecordListResponse:
    """
    Get calibration history for a specific asset.
    """
    asset_service = AssetService(db)
    calibration_service = CalibrationService(db)
    
    # Get asset
    asset = await asset_service.get_by_id(asset_id)
    if not asset:
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    # Check access
    if not current_user.has_location_access(asset.location_id):
        raise NotFoundError(resource="Asset", resource_id=asset_id)
    
    records = await calibration_service.get_asset_history(asset_id)
    
    return CalibrationRecordListResponse(
        items=records,
        total=len(records),
        page=1,
        page_size=len(records),
        pages=1,
    )
