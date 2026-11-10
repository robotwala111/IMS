"""
Transaction Endpoints

Receipt, issue, and return operations.
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_manager_or_admin,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.transaction import TransactionType
from app.schemas.common import MessageResponse
from app.schemas.transaction import (
    TransactionResponse,
    TransactionListResponse,
    ReceiptRequest,
    IssueRequest,
    ReturnRequest,
    TransactionSearchParams,
)
from app.services.transaction_service import TransactionService
from app.services.audit_service import AuditService

logger = get_logger(__name__)
router = APIRouter()


@router.get("", response_model=TransactionListResponse)
async def list_transactions(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    item_id: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    transaction_type: Optional[TransactionType] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    created_by_id: Optional[str] = Query(None),
    reference_number: Optional[str] = Query(None),
) -> TransactionListResponse:
    """
    List transactions with filtering.
    """
    transaction_service = TransactionService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    search_params = TransactionSearchParams(
        item_id=item_id,
        location_id=location_id,
        transaction_type=transaction_type,
        date_from=date_from,
        date_to=date_to,
        created_by_id=created_by_id,
        reference_number=reference_number,
    )
    
    transactions, total = await transaction_service.list_transactions(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "transaction_date",
        sort_order=pagination["sort_order"] or "desc",
        filters=search_params,
        location_ids=location_ids,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return TransactionListResponse(
        items=transactions,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: str,
    current_user: CurrentUser,
    db: DB,
) -> TransactionResponse:
    """
    Get a specific transaction by ID.
    """
    transaction_service = TransactionService(db)
    transaction = await transaction_service.get_by_id(transaction_id)
    
    if not transaction:
        raise NotFoundError(resource="Transaction", resource_id=transaction_id)
    
    # Check access for non-admins
    if not current_user.has_location_access(transaction.location_id):
        raise NotFoundError(resource="Transaction", resource_id=transaction_id)
    
    return transaction


@router.post("/receipt", response_model=MessageResponse)
async def create_receipt(
    request: ReceiptRequest,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Record stock receipt (receiving goods).
    """
    # Check location access
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    transaction_service = TransactionService(db)
    audit_service = AuditService(db)
    
    result = await transaction_service.process_receipt(
        request=request,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="receipt",
        resource_type="transaction",
        resource_id=result["transaction_ids"][0] if result["transaction_ids"] else None,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "location_id": request.location_id,
            "line_count": len(request.line_items),
            "reference": request.reference_number,
        },
    )
    
    return MessageResponse(
        message=f"Receipt processed: {len(request.line_items)} items received",
        data=result,
    )


@router.post("/issue", response_model=MessageResponse)
async def create_issue(
    request: IssueRequest,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Record stock issue (dispensing goods).
    
    Enforces:
    - FIFO for lot-tracked items
    - No issue from expired lots
    - Calibration validation for serialized instruments
    """
    # Check location access
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    transaction_service = TransactionService(db)
    audit_service = AuditService(db)
    
    result = await transaction_service.process_issue(
        request=request,
        user_id=current_user.id,
        is_admin=current_user.is_admin,
    )
    
    # Audit log
    await audit_service.log_action(
        action="issue",
        resource_type="transaction",
        resource_id=result["transaction_ids"][0] if result["transaction_ids"] else None,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "location_id": request.location_id,
            "line_count": len(request.line_items),
            "issued_to": request.issued_to,
            "admin_override": request.admin_override,
        },
    )
    
    return MessageResponse(
        message=f"Issue processed: {len(request.line_items)} items issued",
        data=result,
    )


@router.post("/return", response_model=MessageResponse)
async def create_return(
    request: ReturnRequest,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Record stock return.
    """
    # Check location access
    if not current_user.has_location_access(request.location_id):
        raise NotFoundError(resource="Location", resource_id=request.location_id)
    
    transaction_service = TransactionService(db)
    audit_service = AuditService(db)
    
    result = await transaction_service.process_return(
        request=request,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="return",
        resource_type="transaction",
        resource_id=result["transaction_ids"][0] if result["transaction_ids"] else None,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "location_id": request.location_id,
            "line_count": len(request.line_items),
            "returned_by": request.returned_by,
        },
    )
    
    return MessageResponse(
        message=f"Return processed: {len(request.line_items)} items returned",
        data=result,
    )
