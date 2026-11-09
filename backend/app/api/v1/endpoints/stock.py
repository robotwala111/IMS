"""
Stock Management Endpoints

Stock level queries, adjustments, and lot tracking.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_admin,
    require_manager_or_admin,
)
from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.stock import (
    StockResponse,
    StockListResponse,
    StockAdjustmentRequest,
    StockIssueRequest,
    StockThresholdUpdate,
    StockLocationCorrection,
    StockLotResponse,
    StockLotListResponse,
    StockSearchParams,
    LotSearchParams,
)
from app.services.stock_service import StockService
from app.services.audit_service import AuditService
from app.services.transfer_service import TransferService
from app.schemas.transfer import TransferShipRequest
from app.services.permanent_delete_service import PermanentDeleteService
from app.models.location import Location
from app.models.stock import Stock as StockModel

logger = get_logger(__name__)
router = APIRouter()


def _validate_low_stock_cron_secret(
    secret: Optional[str] = None,
    authorization: Optional[str] = None,
    query_secret: Optional[str] = None,
) -> None:
    if not settings.LOW_STOCK_CRON_SECRET:
        raise AuthorizationError(message="Low stock cron secret is not configured")
    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization.split(" ", 1)[1].strip()
    provided = secret or bearer or query_secret
    if provided != settings.LOW_STOCK_CRON_SECRET:
        raise AuthorizationError(message="Invalid low stock cron secret")


@router.get("/transfer-options", response_model=dict)
async def get_transfer_stock_options(
    current_user: CurrentUser,
    db: DB,
    location_id: str = Query(...),
) -> dict:
    """Return item IDs that currently have transferable stock at an active source."""
    location = (
        await db.execute(
            select(Location).where(
                Location.id == location_id,
                Location.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if not location:
        raise NotFoundError(resource="Active Location", resource_id=location_id)

    result = await db.execute(
        select(StockModel.item_id).where(
            StockModel.location_id == location_id,
            StockModel.is_active.is_(True),
            StockModel.quantity_on_hand > StockModel.quantity_reserved,
        )
    )
    return {"item_ids": list(result.scalars().all())}


@router.get("/available", response_model=dict)
async def get_available_stock(
    current_user: CurrentUser,
    db: DB,
    item_id: str = Query(...),
    location_id: str = Query(...),
) -> dict:
    """
    Get available quantity for a specific item at a specific location.
    Used by Issue Stock modal for real-time availability check.
    """
    # This read-only lookup is used while requesting a transfer from another
    # company location. Transfer creation still enforces destination scope.

    location = (
        await db.execute(
            select(Location).where(
                Location.id == location_id,
                Location.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if not location:
        raise NotFoundError(resource="Active Location", resource_id=location_id)

    result = await db.execute(
        select(StockModel).where(
            StockModel.item_id == item_id,
            StockModel.location_id == location_id,
        )
    )
    stock = result.scalar_one_or_none()
    if not stock:
        return {"on_hand": 0, "reserved": 0, "available": 0}
    on_hand = int(stock.quantity_on_hand or 0)
    reserved = int(stock.quantity_reserved or 0)
    return {"on_hand": on_hand, "reserved": reserved, "available": max(0, on_hand - reserved)}


@router.get("", response_model=StockListResponse)
async def list_stock(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    asset_type: Optional[str] = Query(None),
    low_stock_only: bool = Query(False),
    is_active: Optional[bool] = Query(True),
) -> StockListResponse:
    """
    List stock levels with filtering.
    
    Non-admin users only see stock at their assigned locations.
    """
    stock_service = StockService(db)
    
    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
        # If specific location requested, verify access
        if location_id and location_id not in location_ids:
            raise NotFoundError(resource="Location", resource_id=location_id)
    
    stocks, total = await stock_service.list_stock(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        location_id=location_id,
        item_id=item_id,
        category_id=category_id,
        asset_type=asset_type,
        low_stock_only=low_stock_only,
        location_ids=location_ids,
        is_active=is_active,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return StockListResponse(
        items=stocks,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.post("/adjustments", response_model=MessageResponse)
async def create_adjustment(
    request: StockAdjustmentRequest,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Create a stock adjustment (Manager or Admin).
    """
    # Check location access
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    stock_service = StockService(db)
    audit_service = AuditService(db)
    
    result = await stock_service.adjust_stock(
        item_id=request.item_id,
        location_id=request.location_id,
        quantity_change=request.quantity_change,
        reason=request.reason,
        notes=request.notes,
        lot_id=request.lot_id,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="adjustment",
        resource_type="stock",
        resource_id=result["stock_id"],
        user_id=current_user.id,
        old_value={"quantity": result["old_quantity"]},
        new_value={"quantity": result["new_quantity"], "reason": request.reason},
    )
    
    return MessageResponse(
        message=f"Stock adjusted by {request.quantity_change}",
        data=result,
    )


@router.post("/issue", response_model=MessageResponse)
async def issue_stock(
    request: StockIssueRequest,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Issue stock (Manager or Admin) - deduct quantity-based stock for a process.
    """
    # Check location access
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    stock_service = StockService(db)
    audit_service = AuditService(db)
    
    result = await stock_service.issue_stock(
        item_id=request.item_id,
        location_id=request.location_id,
        to_location_id=request.to_location_id,
        quantity=request.quantity,
        reason=request.reason,
        reference_number=request.reference_number,
        notes=request.notes,
        lot_id=request.lot_id,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="issue",
        resource_type="stock",
        resource_id=result["stock_id"],
        user_id=current_user.id,
        old_value={"quantity": result["old_quantity"]},
        new_value={
            "quantity": result["new_quantity"],
            "reason": request.reason,
            "to_location_id": request.to_location_id,
            "transaction_type": result.get("transaction_type"),
        },
    )
    
    return MessageResponse(
        message=f"Stock issued: {request.quantity} units",
        data=result,
    )


@router.post("/documented-issue", response_model=MessageResponse)
async def create_documented_issue(
    request: StockIssueRequest,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Create a documented stock issue with auto Purchase Indent and Delivery Challan.

    The transfer is approved and shipped immediately so stock is deducted and DC is printable.
    Same-location issues stay shipped/in-transit to avoid adding the stock back to the same location.
    """
    to_location_id = request.to_location_id or request.location_id
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    if not current_user.has_location_access(to_location_id):
        raise NotFoundError(resource="Location", resource_id=to_location_id)

    transfer_service = TransferService(db)
    audit_service = AuditService(db)
    notes = request.notes or request.reason
    transfer = await transfer_service.create_transfer(
        source_location_id=request.location_id,
        destination_location_id=to_location_id,
        items=[{
            "item_id": request.item_id,
            "quantity": request.quantity,
            "notes": notes,
        }],
        requested_by_id=current_user.id,
        notes=notes,
        requires_approval=True,
        transfer_type=request.transfer_type,
        purchase_indent_id=None,
        destination_responsible_id=current_user.id,
    )

    transfer = await transfer_service.approve_transfer(
        transfer_id=transfer.id,
        approved=True,
        notes="Auto-approved for documented stock issue",
        user_id=current_user.id,
        allow_self_approval=True,
    )
    transfer = await transfer_service.ship_transfer(
        transfer_id=transfer.id,
        request=TransferShipRequest(
            shipping_method="Issue Stock",
            tracking_number=request.reference_number,
            notes=notes,
        ),
        user_id=current_user.id,
    )
    transfer = await transfer_service.get_by_id(transfer.id)

    await audit_service.log_action(
        action="documented_issue",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "item_id": request.item_id,
            "from_location_id": request.location_id,
            "to_location_id": to_location_id,
            "quantity": request.quantity,
            "purchase_indent_id": transfer.purchase_indent_id,
            "purchase_indent_number": transfer.purchase_indent_number,
        },
    )

    return MessageResponse(
        message="Stock issued with Purchase Indent and Delivery Challan",
        data={
            "transfer_id": transfer.id,
            "transfer_number": transfer.transfer_number,
            "purchase_indent_id": transfer.purchase_indent_id,
            "purchase_indent_number": transfer.purchase_indent_number,
            "status": transfer.status.value,
        },
    )


@router.patch("/{stock_id}/thresholds", response_model=StockResponse)
async def update_stock_thresholds(
    stock_id: str,
    request: StockThresholdUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> StockResponse:
    """
    Update stock thresholds (min/max/reorder levels).
    """
    stock_service = StockService(db)
    audit_service = AuditService(db)
    
    stock = await stock_service.get_by_id(stock_id)
    if not stock:
        raise NotFoundError(resource="Stock", resource_id=stock_id)
    
    # Check location access
    if not current_user.has_location_access(stock.location_id):
        raise NotFoundError(resource="Stock", resource_id=stock_id)
    
    old_value = {
        "min_level": stock.min_level,
        "max_level": stock.max_level,
        "reorder_point": stock.reorder_point,
    }
    
    updated_stock = await stock_service.update_thresholds(
        stock_id=stock_id,
        **request.model_dump(exclude_unset=True),
    )
    
    # Audit log
    await audit_service.log_action(
        action="update_thresholds",
        resource_type="stock",
        resource_id=stock_id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=request.model_dump(exclude_unset=True),
    )
    
    loaded_stock = await stock_service.get_stock(updated_stock.item_id, updated_stock.location_id)
    return loaded_stock


@router.patch("/{stock_id}/location", response_model=MessageResponse)
async def correct_stock_location(
    stock_id: str,
    request: StockLocationCorrection,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """Move a stock balance to the correct location without changing its totals."""
    stock_service = StockService(db)
    stock = await stock_service.get_by_id(stock_id)
    if not stock:
        raise NotFoundError(resource="Stock", resource_id=stock_id)
    if not current_user.has_location_access(stock.location_id):
        raise AuthorizationError(message="You do not have access to the current location")
    if not current_user.has_location_access(request.location_id):
        raise AuthorizationError(message="You do not have access to the selected location")

    old_location_id = stock.location_id
    result = await stock_service.correct_location(
        stock_id=stock_id,
        new_location_id=request.location_id,
        user_id=current_user.id,
        reason=request.reason,
    )
    await AuditService(db).log_action(
        action="correct_location",
        resource_type="stock",
        resource_id=result["stock_id"],
        user_id=current_user.id,
        old_value={"location_id": old_location_id},
        new_value={
            "location_id": request.location_id,
            "quantity": result["quantity"],
            "merged": result["merged"],
        },
    )
    return MessageResponse(
        message="Stock location corrected without changing quantity",
        data=result,
    )


# Stock Lots

@router.get("/lots", response_model=StockLotListResponse)
async def list_lots(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    lot_number: Optional[str] = Query(None),
    expiring_within_days: Optional[int] = Query(None),
    expired_only: bool = Query(False),
) -> StockLotListResponse:
    """
    List stock lots with filtering.
    """
    stock_service = StockService(db)
    
    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    search_params = LotSearchParams(
        item_id=item_id,
        location_id=location_id,
        lot_number=lot_number,
        expiring_within_days=expiring_within_days,
        expired_only=expired_only,
    )
    
    lots, total = await stock_service.list_lots(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        filters=search_params,
        location_ids=location_ids,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return StockLotListResponse(
        items=lots,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/lots/{lot_id}", response_model=StockLotResponse)
async def get_lot(
    lot_id: str,
    current_user: CurrentUser,
    db: DB,
) -> StockLotResponse:
    """
    Get a specific lot by ID.
    """
    stock_service = StockService(db)
    lot = await stock_service.get_lot_by_id(lot_id)
    
    if not lot:
        raise NotFoundError(resource="Stock Lot", resource_id=lot_id)
    
    # Check access
    if not current_user.has_location_access(lot.location_id):
        raise NotFoundError(resource="Stock Lot", resource_id=lot_id)
    
    return lot


@router.get("/by-location/{location_id}")
async def get_stock_by_location(
    location_id: str,
    current_user: CurrentUser,
    db: DB,
):
    """
    Get stock summary for a location with daily movements.
    
    Shows opening balance, received/issued/adjusted today, and closing balance.
    """
    from app.schemas.stock import LocationStockSummary
    
    # Check access
    if not current_user.has_location_access(location_id):
        raise NotFoundError(resource="Location", resource_id=location_id)
    
    stock_service = StockService(db)
    
    summary = await stock_service.get_location_stock_summary(location_id)
    
    return summary


@router.post("/send-low-stock-alert", response_model=MessageResponse)
async def send_low_stock_alert(
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Manually trigger low stock email alert (Admin/Manager only).

    - Location managers receive alerts only for their assigned location(s).
    - Admins and Head Office Managers receive a company-wide summary.
    - LOW_STOCK_ALERT_EMAILS from config are also included in the summary.
    """
    stock_service = StockService(db)
    result = await stock_service.send_low_stock_alerts()

    if result["count"] == 0:
        return MessageResponse(message="No low stock items found", data={"count": 0})

    if result["recipients"] == 0:
        return MessageResponse(
            message="No email recipients found — assign location managers or configure LOW_STOCK_ALERT_EMAILS",
            data={"count": result["count"], "recipients": 0}
        )

    return MessageResponse(
        message=f"Low stock alert sent to {result['recipients']} recipient(s)",
        data=result,
    )


@router.post("/low-stock-alert/cron", response_model=MessageResponse)
async def send_low_stock_alert_from_cron(
    db: DB,
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
) -> MessageResponse:
    """Serverless-safe automatic low-stock email trigger."""
    _validate_low_stock_cron_secret(x_cron_secret, authorization, secret)
    stock_service = StockService(db)
    result = await stock_service.send_low_stock_alerts()
    if result["count"] == 0:
        return MessageResponse(message="No low stock items found", data=result)
    if result["recipients"] == 0:
        return MessageResponse(
            message="No email recipients found — assign location managers or configure LOW_STOCK_ALERT_EMAILS",
            data=result,
        )
    return MessageResponse(
        message=f"Low stock alert sent to {result['recipients']} recipient(s)",
        data=result,
    )


@router.get("/low-stock-alert/cron", response_model=MessageResponse)
async def send_low_stock_alert_from_cron_get(
    db: DB,
    x_cron_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
) -> MessageResponse:
    """GET variant for cron providers that only support GET."""
    _validate_low_stock_cron_secret(x_cron_secret, authorization, secret)
    stock_service = StockService(db)
    result = await stock_service.send_low_stock_alerts()
    if result["count"] == 0:
        return MessageResponse(message="No low stock items found", data=result)
    if result["recipients"] == 0:
        return MessageResponse(
            message="No email recipients found — assign location managers or configure LOW_STOCK_ALERT_EMAILS",
            data=result,
        )
    return MessageResponse(
        message=f"Low stock alert sent to {result['recipients']} recipient(s)",
        data=result,
    )


@router.delete("/{stock_id}", response_model=MessageResponse)
async def deactivate_stock(
    stock_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """Deactivate a stock row within the caller's location scope."""
    stock_service = StockService(db)
    stock = await stock_service.get_by_id(stock_id)
    if not stock:
        raise NotFoundError(resource="Stock", resource_id=stock_id)
    if not current_user.has_location_access(stock.location_id):
        raise AuthorizationError(message="You do not have access to this location")
    old_active = stock.is_active
    await stock_service.update(stock_id, is_active=False)
    await AuditService(db).log_action(
        action="deactivate", resource_type="stock", resource_id=stock_id,
        user_id=current_user.id, old_value={"is_active": old_active},
        new_value={"is_active": False},
    )
    return MessageResponse(message="Stock record deactivated")


@router.delete("/{stock_id}/permanent", response_model=MessageResponse)
async def permanently_delete_stock(
    stock_id: str,
    current_user: CurrentUser,
    db: DB,
    force: bool = Query(False),
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete an unused stock row (Admin only)."""
    name = await PermanentDeleteService(db).delete(
        "stock", stock_id, current_user, force_stock_balance=force
    )
    return MessageResponse(message=f"Stock record {name} permanently deleted")


# NOTE: This route must be at the end
@router.get("/{stock_id}", response_model=StockResponse)
async def get_stock(
    stock_id: str,
    current_user: CurrentUser,
    db: DB,
) -> StockResponse:
    """
    Get a specific stock record by ID.
    """
    stock_service = StockService(db)
    stock = await stock_service.get_by_id(stock_id)
    
    if not stock:
        raise NotFoundError(resource="Stock", resource_id=stock_id)
    
    # Check access
    if not current_user.has_location_access(stock.location_id):
        raise NotFoundError(resource="Stock", resource_id=stock_id)
    
    return stock
