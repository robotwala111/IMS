"""
Transfer Endpoints

Inter-location transfer workflow with approval.
"""

from typing import Optional, List
from datetime import datetime
import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete as sql_delete, select

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_manager_or_admin,
    require_admin,
)
from app.core.exceptions import NotFoundError, AuthorizationError, BusinessRuleError
from app.core.logging import get_logger
from app.models.branding import AppBranding
from app.models.transfer import Transfer, TransferItem, TransferStatus
from app.models.location import Location
from app.models.user import User, UserRole, user_location_association
from app.schemas.common import MessageResponse
from app.schemas.transfer import (
    TransferCreate,
    TransferResponse,
    TransferListResponse,
    EquipmentTransferOverviewResponse,
    TransferApprovalRequest,
    TransferShipRequest,
    TransferReceiveRequest,
    TransferSearchParams,
    ReturnDateUpdateRequest,
    DCDocumentResponse,
)
from app.services.transfer_service import TransferService
from app.services.generated_document_service import GeneratedDocumentService
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.email_service import get_email_service

logger = get_logger(__name__)
router = APIRouter()


@router.get("", response_model=TransferListResponse)
async def list_transfers(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    from_location_id: Optional[str] = Query(None),
    to_location_id: Optional[str] = Query(None),
    status: Optional[TransferStatus] = Query(None),
    priority: Optional[str] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
    assigned_to_me: bool = Query(False, description="Only transfers assigned to current user"),
    requested_by_me: bool = Query(False, description="Only transfers requested by current user"),
) -> TransferListResponse:
    """
    List transfers with filtering.
    """
    transfer_service = TransferService(db)
    
    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]
    
    # Derive per-user filters
    filter_assigned_to_id = current_user.id if assigned_to_me else None
    filter_requested_by_id = current_user.id if requested_by_me else None

    # When filtering to "my requests" or "for my action", skip the location_ids restriction
    # so users can see transfers they created even from other locations
    if assigned_to_me or requested_by_me:
        location_ids = None
    
    transfers, total = await transfer_service.list_transfers(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "created_at",
        sort_order=pagination["sort_order"] or "desc",
        source_location_id=from_location_id,
        destination_location_id=to_location_id,
        status=status.value if status else None,
        start_date=date_from,
        end_date=date_to,
        location_ids=location_ids,
        assigned_to_id=filter_assigned_to_id,
        requested_by_id=filter_requested_by_id,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return TransferListResponse(
        items=transfers,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/equipment-overview", response_model=EquipmentTransferOverviewResponse)
async def get_equipment_transfer_overview(
    current_user: CurrentUser,
    db: DB,
    location_id: Optional[str] = Query(None),
) -> EquipmentTransferOverviewResponse:
    """Get equipment transfer eligibility grouped by calibration and maintenance."""
    transfer_service = TransferService(db)

    if location_id:
        active_location = (
            await db.execute(
                select(Location).where(
                    Location.id == location_id,
                    Location.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if not active_location:
            raise NotFoundError(resource="Active Location", resource_id=location_id)

    location_ids = None
    if not current_user.has_all_location_access and not location_id:
        location_ids = [loc.id for loc in current_user.assigned_locations]

    overview = await transfer_service.get_equipment_transfer_overview(
        location_id=location_id,
        location_ids=location_ids,
    )
    return EquipmentTransferOverviewResponse(**overview)


# ---------------------------------------------------------------------------
# CSV Export  (must be before /{transfer_id} to avoid route shadowing)
# ---------------------------------------------------------------------------

@router.get("/export")
async def export_transfers_csv(
    current_user: CurrentUser,
    db: DB,
    from_location_id: Optional[str] = Query(None),
    to_location_id: Optional[str] = Query(None),
    status: Optional[TransferStatus] = Query(None),
    date_from: Optional[datetime] = Query(None),
    date_to: Optional[datetime] = Query(None),
) -> StreamingResponse:
    """Export transfers as CSV."""
    transfer_service = TransferService(db)

    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]

    transfers, _ = await transfer_service.list_transfers(
        page=1,
        page_size=10000,
        sort_by="created_at",
        sort_order="desc",
        source_location_id=from_location_id,
        destination_location_id=to_location_id,
        status=status.value if status else None,
        start_date=date_from,
        end_date=date_to,
        location_ids=location_ids,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Transfer No", "PI No", "Type", "Status", "Priority",
        "From Location", "To Location",
        "Requested By", "Approved By",
        "Requested Date", "Required By", "Approved At", "Shipped At", "Received At",
        "Return Date", "Items (SKU:Qty)", "Notes",
    ])

    for t in transfers:
        items_str = "; ".join(
            f"{ti.item_sku or ti.item_id}\u00d7{ti.quantity_requested}"
            for ti in (t.items or [])
        )
        writer.writerow([
            t.transfer_number or "",
            t.purchase_indent_number or "",
            t.transfer_type or "",
            t.status.value if t.status else "",
            t.priority or "",
            t.from_location_name or t.from_location_id or "",
            t.to_location_name or t.to_location_id or "",
            t.requested_by_name or "",
            t.approved_by_name or "",
            t.requested_date.strftime("%Y-%m-%d") if t.requested_date else "",
            t.required_by_date.strftime("%Y-%m-%d") if t.required_by_date else "",
            t.approved_at.strftime("%Y-%m-%d %H:%M") if t.approved_at else "",
            t.shipped_at.strftime("%Y-%m-%d %H:%M") if t.shipped_at else "",
            t.received_at.strftime("%Y-%m-%d %H:%M") if t.received_at else "",
            t.return_date.strftime("%Y-%m-%d") if t.return_date else "",
            items_str,
            t.request_notes or "",
        ])

    output.seek(0)
    filename = f"transfers_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{transfer_id}", response_model=TransferResponse)
async def get_transfer(
    transfer_id: str,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Get a specific transfer by ID.
    """
    transfer_service = TransferService(db)
    transfer = await transfer_service.get_by_id(transfer_id)
    
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    
    # Check access for non-admins
    if not current_user.has_all_location_access:
        has_access = (
            current_user.has_location_access(transfer.from_location_id) or
            current_user.has_location_access(transfer.to_location_id)
        )
        if not has_access:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    
    return transfer


@router.post("", response_model=TransferResponse, status_code=201)
async def create_transfer(
    request: TransferCreate,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Create a new transfer request.
    """
    if (
        not current_user.has_all_location_access
        and not current_user.has_location_access(request.to_location_id)
    ):
        raise AuthorizationError(
            message="Location Managers can request transfers only to their assigned location"
        )

    if request.from_location_id == request.to_location_id and not request.destination_responsible_id:
        raise BusinessRuleError(
            message="Select a destination responsible person for same-location local transfers"
        )

    location_result = await db.execute(
        select(Location).where(
            Location.id.in_([request.from_location_id, request.to_location_id])
        )
    )
    locations_by_id = {location.id: location for location in location_result.scalars()}
    for location_id, label in (
        (request.from_location_id, "Source"),
        (request.to_location_id, "Destination"),
    ):
        location = locations_by_id.get(location_id)
        if not location:
            raise NotFoundError(resource=f"{label} Location", resource_id=location_id)
        if not location.is_active:
            raise BusinessRuleError(message=f"{label} location is inactive")

    async def validate_responsible_user(user_id: str, location_id: str, label: str) -> None:
        result = await db.execute(
            select(User)
            .join(user_location_association, user_location_association.c.user_id == User.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                User.role == UserRole.LOCATION_MANAGER,
                user_location_association.c.location_id == location_id,
            )
        )
        if not result.scalar_one_or_none():
            raise BusinessRuleError(
                message=f"{label} must be an active Location Manager assigned to the selected location"
            )

    await validate_responsible_user(
        request.assigned_to_id,
        request.from_location_id,
        "Source responsible person",
    )
    if request.destination_responsible_id:
        await validate_responsible_user(
            request.destination_responsible_id,
            request.to_location_id,
            "Destination responsible person",
        )

    request_notes = request.request_notes
    if request.local_receiving_details:
        detail = request.local_receiving_details.strip()
        request_notes = "\n".join(
            part
            for part in [request_notes, f"Same-location receiving details: {detail}"]
            if part
        )
    
    transfer_service = TransferService(db)
    audit_service = AuditService(db)
    
    # Convert request items to the format expected by the service
    items = [
        {
            "item_id": item.item_id,
            "quantity": item.quantity_requested,
            "lot_number": item.lot_number,
            "serial_numbers": item.serial_numbers,
            "notes": item.notes,
        }
        for item in request.items
    ]
    
    try:
        transfer = await transfer_service.create_transfer(
            source_location_id=request.from_location_id,
            destination_location_id=request.to_location_id,
            items=items,
            requested_by_id=current_user.id,
            notes=request_notes,
            requires_approval=True,
            transfer_type=request.transfer_type,
            required_by_date=request.required_by_date,
            return_date=request.return_date,
            purchase_indent_id=request.purchase_indent_id,
            assigned_to_id=request.assigned_to_id,
            destination_responsible_id=request.destination_responsible_id,
        )
    except BusinessRuleError as exc:
        await audit_service.log_action(
            action="transfer_blocked",
            resource_type="transfer_attempt",
            resource_id="pending",
            user_id=current_user.id,
            old_value=None,
            new_value={
                "from_location_id": request.from_location_id,
                "to_location_id": request.to_location_id,
                "item_count": len(request.items),
                "error_code": exc.error_code,
                "details": exc.details,
            },
        )
        raise
    
    # Audit log
    await audit_service.log_action(
        action="create",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "transfer_number": transfer.transfer_number,
            "from_location_id": transfer.from_location_id,
            "to_location_id": transfer.to_location_id,
            "item_count": len(request.items),
        },
    )

    # Notify from_location managers — UI notification + email
    try:
        notif_service = NotificationService(db)
        email_service = get_email_service()

        # Find managers assigned to the supplying (from) location
        mgr_result = await db.execute(
            select(User)
            .join(user_location_association, user_location_association.c.user_id == User.id)
            .where(
                user_location_association.c.location_id == transfer.from_location_id,
                User.role.in_([UserRole.LOCATION_MANAGER, UserRole.HEAD_OFFICE_MANAGER, UserRole.ADMIN]),
                User.is_active == True,
            )
        )
        managers: List[User] = list(mgr_result.scalars().unique().all())

        notif_title = f"Transfer Request {transfer.transfer_number}"
        notif_body = (
            f"{current_user.name} from {transfer.to_location_name or transfer.to_location_id} "
            f"has requested a transfer of {len(transfer.items)} item(s) from your location. "
            f"PI: {transfer.purchase_indent_number or 'pending'}. "
            f"Please review and approve/reject."
        )
        if managers:
            await notif_service.create_bulk_notifications(
                user_ids=[m.id for m in managers],
                notification_type="transfer_request",
                title=notif_title,
                message=notif_body,
                data={"transfer_id": transfer.id, "transfer_number": transfer.transfer_number},
            )
            # Email
            mgr_emails = [m.email for m in managers if m.email]
            if mgr_emails:
                items_data = [
                    {
                        "sku": ti.item_sku or "",
                        "name": ti.item_name or "",
                        "quantity_requested": ti.quantity_requested,
                        "notes": ti.notes or "",
                    }
                    for ti in transfer.items
                ]
                sent = email_service.send_transfer_request_alert(
                    to_emails=mgr_emails,
                    transfer_number=transfer.transfer_number,
                    pi_number=transfer.purchase_indent_number or "pending",
                    from_location=transfer.from_location_name or transfer.from_location_id,
                    to_location=transfer.to_location_name or transfer.to_location_id,
                    requester_name=current_user.name,
                    items=items_data,
                    priority=transfer.priority,
                    required_by_date=transfer.required_by_date.strftime("%Y-%m-%d") if transfer.required_by_date else None,
                    notes=transfer.request_notes,
                )
                if not sent:
                    await notif_service.enqueue_email(
                        recipient_emails=mgr_emails,
                        notification_type="transfer_request",
                        subject=notif_title,
                        body_html=f"<p>{notif_body}</p>", body_text=notif_body,
                        reference_type="transfer", reference_id=transfer.id,
                        dedup_key=f"transfer-request:{transfer.id}",
                    )
    except Exception as exc:
        logger.warning("Failed to send transfer request notifications: %s", exc)

    transfer = await transfer_service.get_by_id(transfer.id)
    return transfer


@router.patch("/{transfer_id}/approve", response_model=TransferResponse)
async def approve_transfer(
    transfer_id: str,
    request: TransferApprovalRequest,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Approve or reject a transfer request (Manager or Admin).
    """
    transfer_service = TransferService(db)
    audit_service = AuditService(db)
    
    transfer = await transfer_service.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    
    # Allow: admin/head-office, managers with location access, OR the specifically assigned user
    is_assigned_user = (transfer.assigned_to_id == current_user.id)
    has_location_access = current_user.has_location_access(transfer.from_location_id)
    if not (current_user.has_all_location_access or has_location_access or is_assigned_user):
        raise AuthorizationError(message="You are not authorised to approve this transfer")
    
    if transfer.status != TransferStatus.REQUESTED:
        raise BusinessRuleError(
            message=f"Cannot approve transfer in status '{transfer.status.value}'",
            rule_code="INVALID_STATUS_TRANSITION",
        )
    
    old_status = transfer.status.value
    
    updated_transfer = await transfer_service.approve_transfer(
        transfer_id=transfer_id,
        approved=request.approved,
        notes=request.notes,
        rejection_reason=request.rejection_reason,
        user_id=current_user.id,
        allow_self_approval=current_user.role == UserRole.ADMIN,
    )
    
    # Audit log
    await audit_service.log_action(
        action="approve" if request.approved else "reject",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": updated_transfer.status.value},
    )

    # Send DC email + in-app notification to the requester on approval
    if request.approved:
        try:
            notif_service = NotificationService(db)
            email_service = get_email_service()

            dc_number = updated_transfer.dc_number
            items_data = [
                {
                    "sku": ti.item_sku or "",
                    "name": ti.item_name or "",
                    "quantity_requested": ti.quantity_requested,
                    "quantity_shipped": ti.quantity_shipped,
                    "lot_number": ti.lot_number or "",
                }
                for ti in updated_transfer.items
            ]

            # In-app notification to the original requester
            await notif_service.create_notification(
                user_id=updated_transfer.requested_by_id,
                notification_type="transfer_approved",
                title=f"Transfer Approved — {dc_number} Ready",
                message=(
                    f"Your transfer request {updated_transfer.transfer_number} from "
                    f"{updated_transfer.from_location_name or updated_transfer.from_location_id} "
                    f"has been approved. Delivery Challan {dc_number} has been generated."
                ),
                data={
                    "transfer_id": updated_transfer.id,
                    "transfer_number": updated_transfer.transfer_number,
                    "dc_number": dc_number,
                    "pi_number": updated_transfer.purchase_indent_number,
                },
            )

            # Email DC to requester
            requester_result = await db.execute(
                select(User).where(User.id == updated_transfer.requested_by_id)
            )
            requester = requester_result.scalar_one_or_none()
            if requester and requester.email:
                sent = email_service.send_delivery_challan_email(
                    to_emails=[requester.email],
                    dc_number=dc_number,
                    transfer_number=updated_transfer.transfer_number,
                    pi_number=updated_transfer.purchase_indent_number,
                    from_location=updated_transfer.from_location_name or updated_transfer.from_location_id,
                    to_location=updated_transfer.to_location_name or updated_transfer.to_location_id,
                    approved_by_name=current_user.name,
                    items=items_data,
                    shipping_notes=updated_transfer.approval_notes,
                )
                if not sent:
                    body = (
                        f"Transfer {updated_transfer.transfer_number} was approved. "
                        f"Delivery Challan: {dc_number}."
                    )
                    await notif_service.enqueue_email(
                        recipient_emails=[requester.email],
                        notification_type="transfer_approved",
                        subject=f"Transfer Approved — {dc_number}",
                        body_html=f"<p>{body}</p>", body_text=body,
                        recipient_id=requester.id, reference_type="transfer",
                        reference_id=updated_transfer.id,
                        dedup_key=f"transfer-approved:{updated_transfer.id}",
                    )
        except Exception as exc:
            logger.warning("Failed to send DC notification/email: %s", exc)

    updated_transfer = await transfer_service.get_by_id(updated_transfer.id)
    return updated_transfer


@router.patch("/{transfer_id}/ship", response_model=TransferResponse)
async def ship_transfer(
    transfer_id: str,
    request: TransferShipRequest,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Mark transfer as shipped.
    """
    transfer_service = TransferService(db)
    audit_service = AuditService(db)
    
    transfer = await transfer_service.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    
    # Check access to source location
    if not current_user.has_location_access(transfer.from_location_id):
        raise AuthorizationError(message="You can only ship transfers from your assigned locations")
    
    if transfer.status not in (
        TransferStatus.APPROVED,
        TransferStatus.IN_TRANSIT,
        TransferStatus.PARTIALLY_RECEIVED,
    ):
        raise BusinessRuleError(
            message=f"Cannot ship transfer in status '{transfer.status.value}'",
            rule_code="INVALID_STATUS_TRANSITION",
        )
    
    old_status = transfer.status.value
    updated_transfer = await transfer_service.ship_transfer(
        transfer_id=transfer_id,
        request=request,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="ship",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": updated_transfer.status.value},
    )
    
    updated_transfer = await transfer_service.get_by_id(updated_transfer.id)
    return updated_transfer


@router.patch("/{transfer_id}/receive", response_model=TransferResponse)
async def receive_transfer(
    transfer_id: str,
    request: TransferReceiveRequest,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Receive a transfer at destination location.
    """
    transfer_service = TransferService(db)
    audit_service = AuditService(db)
    
    transfer = await transfer_service.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    
    # Check access to destination location
    if not current_user.has_location_access(transfer.to_location_id):
        raise AuthorizationError(message="You can only receive transfers at your assigned locations")
    
    if transfer.status not in (
        TransferStatus.IN_TRANSIT,
        TransferStatus.PARTIALLY_RECEIVED,
    ):
        raise BusinessRuleError(
            message=f"Cannot receive transfer in status '{transfer.status.value}'",
            rule_code="INVALID_STATUS_TRANSITION",
        )
    
    old_status = transfer.status.value
    updated_transfer = await transfer_service.receive_transfer(
        transfer_id=transfer_id,
        request=request,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="receive",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": updated_transfer.status.value},
    )
    
    updated_transfer = await transfer_service.get_by_id(updated_transfer.id)
    return updated_transfer


@router.patch("/{transfer_id}/cancel", response_model=TransferResponse)
async def cancel_transfer(
    transfer_id: str,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Cancel a transfer request.
    """
    transfer_service = TransferService(db)
    audit_service = AuditService(db)
    
    transfer = await transfer_service.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    
    # Check access
    if not current_user.has_all_location_access:
        has_access = (
            current_user.has_location_access(transfer.from_location_id) or
            transfer.requested_by_id == current_user.id
        )
        if not has_access:
            raise AuthorizationError(message="You do not have permission to cancel this transfer")
    
    # Can only cancel requested or approved transfers
    if transfer.status not in [TransferStatus.REQUESTED, TransferStatus.APPROVED]:
        raise BusinessRuleError(
            message=f"Cannot cancel transfer in status '{transfer.status.value}'",
            rule_code="INVALID_STATUS_TRANSITION",
        )
    
    old_status = transfer.status.value
    
    updated_transfer = await transfer_service.cancel_transfer(
        transfer_id=transfer_id,
        user_id=current_user.id,
    )
    
    # Audit log
    await audit_service.log_action(
        action="cancel",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value={"status": old_status},
        new_value={"status": TransferStatus.CANCELLED.value},
    )
    
    updated_transfer = await transfer_service.get_by_id(updated_transfer.id)
    return updated_transfer


@router.patch("/{transfer_id}/return-date", response_model=TransferResponse)
async def update_return_date(
    transfer_id: str,
    request: ReturnDateUpdateRequest,
    current_user: CurrentUser,
    db: DB,
) -> TransferResponse:
    """
    Update the return date for an equipment transfer.
    Requires a reason for the modification.
    """
    transfer_service = TransferService(db)
    audit_service = AuditService(db)

    transfer = await transfer_service.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)

    # Check access
    if not current_user.has_all_location_access:
        has_access = (
            current_user.has_location_access(transfer.from_location_id)
            or current_user.has_location_access(transfer.to_location_id)
            or transfer.requested_by_id == current_user.id
        )
        if not has_access:
            raise AuthorizationError(message="You do not have permission to modify this transfer")

    # Cannot modify cancelled/rejected transfers
    if transfer.status in [TransferStatus.CANCELLED, TransferStatus.REJECTED]:
        raise BusinessRuleError(
            message=f"Cannot modify return date for transfer in status '{transfer.status.value}'",
            rule_code="INVALID_STATUS_TRANSITION",
        )

    old_return_date = transfer.return_date.isoformat() if transfer.return_date else None

    updated = await transfer_service.update_return_date(
        transfer_id=transfer_id,
        return_date=request.return_date,
        reason=request.reason,
        return_reminder_days=request.return_reminder_days,
    )

    await audit_service.log_action(
        action="update_return_date",
        resource_type="transfer",
        resource_id=transfer.id,
        user_id=current_user.id,
        old_value={"return_date": old_return_date},
        new_value={"return_date": request.return_date.isoformat(), "reason": request.reason, "return_reminder_days": request.return_reminder_days},
    )

    updated = await transfer_service.get_by_id(updated.id)
    return updated


# ---------------------------------------------------------------------------
# Delivery Challan (DC) document
# ---------------------------------------------------------------------------

@router.get("/{transfer_id}/dc", response_model=DCDocumentResponse)
async def get_delivery_challan(
    transfer_id: str,
    current_user: CurrentUser,
    db: DB,
) -> DCDocumentResponse:
    """
    Return structured Delivery Challan (DC) data for a shipped/received transfer.
    Only available when the transfer is IN_TRANSIT or beyond.
    """
    transfer_service = TransferService(db)
    transfer = await transfer_service.get_by_id(transfer_id)
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)

    if transfer.status not in [
        TransferStatus.APPROVED,
        TransferStatus.IN_TRANSIT,
        TransferStatus.RECEIVED,
        TransferStatus.PARTIALLY_RECEIVED,
    ]:
        raise BusinessRuleError(
            message=(
                "Delivery Challan is only available for approved or shipped transfers "
                f"(current status: {transfer.status.value})"
            ),
            rule_code="DC_NOT_AVAILABLE",
        )

    # Access check
    if not current_user.has_all_location_access:
        has_access = (
            current_user.has_location_access(transfer.from_location_id)
            or current_user.has_location_access(transfer.to_location_id)
        )
        if not has_access:
            raise AuthorizationError(message="You do not have access to this transfer")

    shipped_by_name = "N/A"
    if transfer.shipped_by_id:
        from app.services.user_service import UserService
        user_service = UserService(db)
        shipped_user = await user_service.get_by_id(transfer.shipped_by_id)
        if shipped_user:
            shipped_by_name = shipped_user.name

    items_data = []
    for line in transfer.items:
        items_data.append(
            {
                "item_id": line.item_id,
                "sku": line.item_sku or "",
                "name": line.item_name or "",
                "quantity_requested": line.quantity_requested,
                "quantity_shipped": line.quantity_shipped,
                "quantity_received": line.quantity_received,
                "lot_number": line.lot_number or "",
                "serial_numbers": line.serial_numbers or [],
                "notes": line.notes or "",
            }
        )

    shipped_at = transfer.shipped_at or transfer.updated_at
    dc_date = shipped_at.strftime("%d-%m-%Y") if shipped_at else ""
    ref_date = transfer.created_at.strftime("%d-%m-%Y") if transfer.created_at else dc_date
    branding_result = await db.execute(select(AppBranding).where(AppBranding.id == "default"))
    branding = branding_result.scalar_one_or_none()

    def format_location_address(location) -> str:
        if not location:
            return ""
        return ", ".join(
            str(part).strip()
            for part in (
                location.address,
                location.city,
                location.state,
                location.postal_code,
                location.country,
            )
            if part and str(part).strip()
        )

    dc_number = await transfer_service.ensure_dc_number(transfer)
    await db.commit()

    try:
        doc_service = GeneratedDocumentService(db)
        await doc_service.generate_and_store_dc_pdf(transfer.id, generated_by_id=current_user.id)
    except Exception as exc:
        logger.warning("Failed to store generated DC document: %s", exc)

    return DCDocumentResponse(
        dc_number=dc_number,
        transfer_number=transfer.transfer_number,
        transfer_type=transfer.transfer_type,
        indent_number=transfer.purchase_indent_number,
        dc_date=dc_date,
        ref_date=ref_date,
        company_name=branding.company_name if branding else "M/s Scientech Services",
        logo_data_url=branding.logo_data_url if branding else None,
        issued_by=shipped_by_name if shipped_by_name != "N/A" else (current_user.name or current_user.email),
        from_location=transfer.from_location_name or transfer.from_location_id,
        from_location_address=format_location_address(transfer.from_location),
        to_location=transfer.to_location_name or transfer.to_location_id,
        to_location_address=format_location_address(transfer.to_location),
        shipped_by=shipped_by_name,
        items=items_data,
        shipping_notes=(
            transfer.shipping_notes
            or transfer.approval_notes
            or transfer.request_notes
        ),
    )


@router.delete("/{transfer_id}/permanent", response_model=MessageResponse)
async def permanently_delete_transfer(
    transfer_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete a transfer and its line items (Admin only)."""
    result = await db.execute(select(Transfer).where(Transfer.id == transfer_id))
    transfer = result.scalar_one_or_none()
    if not transfer:
        raise NotFoundError(resource="Transfer", resource_id=transfer_id)
    line_ids = (await db.execute(
        select(TransferItem.id).where(TransferItem.transfer_id == transfer_id)
    )).scalars().all()
    transfer_number = transfer.transfer_number
    await db.execute(sql_delete(TransferItem).where(TransferItem.transfer_id == transfer_id))
    await db.execute(sql_delete(Transfer).where(Transfer.id == transfer_id))
    await AuditService(db).log_action(
        action="permanent_delete", resource_type="transfer",
        resource_id=transfer_id, user_id=current_user.id,
        old_value={"transfer_number": transfer_number, "line_items_deleted": len(line_ids)},
        new_value=None,
    )
    return MessageResponse(
        message=f"Transfer {transfer_number} and {len(line_ids)} line item(s) permanently deleted"
    )
