"""
Purchase Indent Endpoints

Purchase Indents (PI) are auto-created by the transfer service when a transfer
request is submitted.  These read-only endpoints expose PI data so the frontend
can display and print PI documents from within the Transfer workflow.

Manual PI creation / approval / cancellation is intentionally not exposed here;
the full PI lifecycle is managed internally by the transfer approval flow.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_location_access,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.branding import AppBranding
from app.services.generated_document_service import GeneratedDocumentService
from app.schemas.purchase_indent import (
    PurchaseIndentDocumentResponse,
    PurchaseIndentListResponse,
    PurchaseIndentResponse,
)
from app.services.purchase_indent_service import PurchaseIndentService

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# List  (managers can see all PIs linked to their transfers)
# ---------------------------------------------------------------------------

@router.get("", response_model=PurchaseIndentListResponse)
async def list_purchase_indents(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> PurchaseIndentListResponse:
    """List Purchase Indents accessible to the current user."""
    service = PurchaseIndentService(db)

    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]

    indents, total = await service.list_indents(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "created_at",
        sort_order=pagination["sort_order"] or "desc",
        status=status,
        location_ids=location_ids,
        search=search,
    )

    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    return PurchaseIndentListResponse(
        items=indents,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


# ---------------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------------

@router.get("/{indent_id}", response_model=PurchaseIndentResponse)
async def get_purchase_indent(
    indent_id: str,
    current_user: CurrentUser,
    db: DB,
) -> PurchaseIndentResponse:
    """Get a single Purchase Indent by ID."""
    service = PurchaseIndentService(db)
    indent = await service.get_by_id(indent_id)
    if not indent:
        raise NotFoundError(resource="PurchaseIndent", resource_id=indent_id)
    if not current_user.has_all_location_access:
        allowed = (
            current_user.has_location_access(indent.requested_by_location_id)
            or (
                indent.supplying_location_id
                and current_user.has_location_access(indent.supplying_location_id)
            )
        )
        if not allowed:
            require_location_access(current_user, indent.requested_by_location_id)
    return indent


# ---------------------------------------------------------------------------
# Printable PI document data
# ---------------------------------------------------------------------------

@router.get("/{indent_id}/document", response_model=PurchaseIndentDocumentResponse)
async def get_pi_document(
    indent_id: str,
    current_user: CurrentUser,
    db: DB,
) -> PurchaseIndentDocumentResponse:
    """Return structured PI data for generating a printable document."""
    service = PurchaseIndentService(db)
    indent = await service.get_by_id(indent_id)
    if not indent:
        raise NotFoundError(resource="PurchaseIndent", resource_id=indent_id)
    if not current_user.has_all_location_access:
        allowed = (
            current_user.has_location_access(indent.requested_by_location_id)
            or (
                indent.supplying_location_id
                and current_user.has_location_access(indent.supplying_location_id)
            )
        )
        if not allowed:
            require_location_access(current_user, indent.requested_by_location_id)

    items_data = [
        {
            "item_id": line.item_id,
            "sku": line.item_sku or "",
            "name": line.item_name or "",
            "unit": line.item_unit or "",
            "quantity_requested": line.quantity_requested,
            "quantity_approved": line.quantity_approved,
            "quantity_fulfilled": line.quantity_fulfilled,
            "notes": line.notes or "",
        }
        for line in indent.items
    ]

    transfers_data = [
        {
            "transfer_number": t.transfer_number,
            "status": t.status,
            "shipped_date": t.updated_at.isoformat() if t.updated_at else "",
        }
        for t in (indent.transfers or [])
    ]

    branding_result = await db.execute(select(AppBranding).where(AppBranding.id == "default"))
    branding = branding_result.scalar_one_or_none()
    try:
        doc_service = GeneratedDocumentService(db)
        await doc_service.generate_and_store_pi_pdf(indent.id, generated_by_id=current_user.id)
    except Exception as exc:
        logger.warning("Failed to store generated PI document: %s", exc)

    return PurchaseIndentDocumentResponse(
        indent_number=indent.indent_number,
        indent_date=indent.indent_date.strftime("%d-%m-%Y"),
        printed_by=current_user.name or current_user.email,
        printed_date=datetime.now().strftime("%d-%m-%Y"),
        company_name=branding.company_name if branding else "M/s. SCIENTECH SERVICES",
        app_name=branding.app_name if branding else "Scientech-IMS",
        logo_data_url=branding.logo_data_url if branding else None,
        required_by_date=indent.required_by_date.isoformat() if indent.required_by_date else None,
        requesting_location=indent.requesting_location_name or indent.requested_by_location_id,
        supplying_location=indent.supplying_location_name,
        requested_by=indent.requested_by_name or indent.requested_by_id,
        approved_by=indent.approved_by_name,
        status=indent.status.value,
        purpose=indent.purpose,
        notes=indent.notes,
        items=items_data,
        transfers=transfers_data,
    )

