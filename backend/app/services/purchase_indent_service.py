"""
Purchase Indent Service

Handles creation, approval, and lifecycle management of Purchase Indents.
A Purchase Indent (PI) must exist and be approved before a Delivery Challan
(DC / Transfer) can be raised against it.
"""

import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.item import Item
from app.models.location import Location
from app.models.purchase_indent import (
    PurchaseIndent,
    PurchaseIndentItem,
    PurchaseIndentStatus,
)
from app.services.base_service import BaseService


class PurchaseIndentService(BaseService[PurchaseIndent]):
    """Service for Purchase Indent management."""

    @property
    def model(self):
        return PurchaseIndent

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def generate_indent_number(self, location_id: str) -> str:
        """Generate SS/<location code>/<running serial> for a requesting location."""
        location_result = await self.db.execute(
            select(Location)
            .where(Location.id == location_id)
            .with_for_update()
        )
        location = location_result.scalar_one_or_none()
        if not location:
            raise NotFoundError(resource="Location", resource_id=location_id)

        location_code = re.sub(r"[^A-Z0-9_-]", "-", location.code.strip().upper())
        prefix = f"SS/{location_code}/"
        existing_result = await self.db.execute(
            select(PurchaseIndent.indent_number).where(
                PurchaseIndent.indent_number.like(f"{prefix}%")
            )
        )
        serials = []
        for number in existing_result.scalars():
            suffix = number[len(prefix):]
            if suffix.isdigit():
                serials.append(int(suffix))

        return f"{prefix}{max(serials, default=0) + 1:04d}"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, id: str) -> Optional[PurchaseIndent]:
        result = await self.db.execute(
            select(PurchaseIndent)
            .options(
                selectinload(PurchaseIndent.requesting_location),
                selectinload(PurchaseIndent.supplying_location),
                selectinload(PurchaseIndent.requested_by),
                selectinload(PurchaseIndent.approved_by),
                selectinload(PurchaseIndent.items).selectinload(PurchaseIndentItem.item),
                selectinload(PurchaseIndent.transfers),
            )
            .where(PurchaseIndent.id == id)
        )
        return result.scalar_one_or_none()

    async def get_by_indent_number(self, indent_number: str) -> Optional[PurchaseIndent]:
        result = await self.db.execute(
            select(PurchaseIndent)
            .options(
                selectinload(PurchaseIndent.requesting_location),
                selectinload(PurchaseIndent.supplying_location),
                selectinload(PurchaseIndent.requested_by),
                selectinload(PurchaseIndent.approved_by),
                selectinload(PurchaseIndent.items).selectinload(PurchaseIndentItem.item),
            )
            .where(PurchaseIndent.indent_number == indent_number)
        )
        return result.scalar_one_or_none()

    async def list_indents(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        status: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[PurchaseIndent], int]:
        query = select(PurchaseIndent).options(
            selectinload(PurchaseIndent.requesting_location),
            selectinload(PurchaseIndent.supplying_location),
            selectinload(PurchaseIndent.requested_by),
            selectinload(PurchaseIndent.items).selectinload(PurchaseIndentItem.item),
        )

        if location_ids is not None:
            query = query.where(
                or_(
                    PurchaseIndent.requested_by_location_id.in_(location_ids),
                    PurchaseIndent.supplying_location_id.in_(location_ids),
                )
            )

        if status:
            query = query.where(PurchaseIndent.status == status)

        if search:
            pat = f"%{search}%"
            query = query.where(
                or_(
                    PurchaseIndent.indent_number.ilike(pat),
                    PurchaseIndent.purpose.ilike(pat),
                )
            )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        if hasattr(PurchaseIndent, sort_by):
            col = getattr(PurchaseIndent, sort_by)
            query = query.order_by(col.desc() if sort_order == "desc" else col.asc())

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        return list(result.scalars().unique().all()), total

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_indent(
        self,
        requested_by_location_id: str,
        items: List[dict],
        requested_by_id: str,
        supplying_location_id: Optional[str] = None,
        required_by_date: Optional[datetime] = None,
        purpose: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> PurchaseIndent:
        # Validate requesting location
        loc_result = await self.db.execute(
            select(Location).where(Location.id == requested_by_location_id)
        )
        if not loc_result.scalar_one_or_none():
            raise NotFoundError(resource="Location", resource_id=requested_by_location_id)

        # Validate supplying location if provided
        if supplying_location_id:
            loc2 = await self.db.execute(
                select(Location).where(Location.id == supplying_location_id)
            )
            if not loc2.scalar_one_or_none():
                raise NotFoundError(resource="Location", resource_id=supplying_location_id)

        indent = PurchaseIndent(
            id=self.generate_id(),
            indent_number=await self.generate_indent_number(requested_by_location_id),
            requested_by_location_id=requested_by_location_id,
            supplying_location_id=supplying_location_id,
            requested_by_id=requested_by_id,
            indent_date=datetime.now(timezone.utc),
            required_by_date=required_by_date,
            purpose=purpose,
            notes=notes,
            status=PurchaseIndentStatus.SUBMITTED,
        )
        self.db.add(indent)
        await self.db.flush()

        for item_data in items:
            item_id = item_data["item_id"]
            qty = int(item_data["quantity_requested"])
            if qty <= 0:
                raise BadRequestError(message="Item quantity must be positive")

            item_result = await self.db.execute(select(Item).where(Item.id == item_id))
            if not item_result.scalar_one_or_none():
                raise NotFoundError(resource="Item", resource_id=item_id)

            line = PurchaseIndentItem(
                id=self.generate_id(),
                indent_id=indent.id,
                item_id=item_id,
                quantity_requested=qty,
                quantity_approved=0,
                quantity_fulfilled=0,
                notes=item_data.get("notes"),
            )
            self.db.add(line)

        await self.db.commit()
        return await self.get_by_id(indent.id)

    # ------------------------------------------------------------------
    # Approve / Reject
    # ------------------------------------------------------------------

    async def approve_indent(
        self,
        indent_id: str,
        approved: bool,
        user_id: str,
        notes: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        approved_items: Optional[List[dict]] = None,
    ) -> PurchaseIndent:
        indent = await self.get_by_id(indent_id)
        if not indent:
            raise NotFoundError(resource="PurchaseIndent", resource_id=indent_id)

        if indent.status not in (
            PurchaseIndentStatus.SUBMITTED,
            PurchaseIndentStatus.DRAFT,
        ):
            raise BadRequestError(
                message=f"Cannot approve indent with status '{indent.status}'"
            )

        if approved:
            # Apply per-line approved quantities if provided
            if approved_items is not None:
                line_ids = {line.id for line in indent.items}
                supplied_ids = [a.get("indent_item_id") for a in approved_items]
                if len(supplied_ids) != len(set(supplied_ids)):
                    raise BadRequestError(message="Approved item line IDs must not be duplicated")
                if set(supplied_ids) != line_ids:
                    raise BadRequestError(
                        message="Approved quantities must include every PI line exactly once"
                    )
                approved_map = {
                    a["indent_item_id"]: int(a["quantity_approved"])
                    for a in approved_items
                }
                for line in indent.items:
                    approved_qty = approved_map[line.id]
                    if approved_qty < 0 or approved_qty > line.quantity_requested:
                        raise BadRequestError(
                            message=f"Approved quantity for line {line.id} must be between 0 and {line.quantity_requested}"
                        )
                    line.quantity_approved = approved_qty
            else:
                for line in indent.items:
                    line.quantity_approved = line.quantity_requested

            indent.status = PurchaseIndentStatus.APPROVED
            indent.approved_by_id = user_id
            indent.approved_at = datetime.now(timezone.utc)
        else:
            indent.status = PurchaseIndentStatus.REJECTED
            indent.rejection_reason = rejection_reason or notes

        await self.db.commit()
        return await self.get_by_id(indent_id)

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    async def cancel_indent(self, indent_id: str) -> PurchaseIndent:
        indent = await self.get_by_id(indent_id)
        if not indent:
            raise NotFoundError(resource="PurchaseIndent", resource_id=indent_id)

        if indent.status in (
            PurchaseIndentStatus.FULFILLED,
            PurchaseIndentStatus.CANCELLED,
        ):
            raise BadRequestError(
                message=f"Cannot cancel indent with status '{indent.status}'"
            )

        indent.status = PurchaseIndentStatus.CANCELLED
        await self.db.commit()
        return await self.get_by_id(indent_id)

    # ------------------------------------------------------------------
    # Update fulfilled quantity (called by transfer service on receive)
    # ------------------------------------------------------------------

    async def record_fulfillment(
        self, indent_id: str, item_id: str, quantity_received: int
    ) -> None:
        """Increment fulfilled qty on the matching PI line and update PI status."""
        indent = await self.get_by_id(indent_id)
        if not indent:
            return

        for line in indent.items:
            if line.item_id == item_id:
                line.quantity_fulfilled = min(
                    line.quantity_approved,
                    line.quantity_fulfilled + quantity_received,
                )

        # Determine new status
        total_approved = sum(l.quantity_approved for l in indent.items)
        total_fulfilled = sum(l.quantity_fulfilled for l in indent.items)

        if total_fulfilled >= total_approved and total_approved > 0:
            indent.status = PurchaseIndentStatus.FULFILLED
        elif total_fulfilled > 0:
            indent.status = PurchaseIndentStatus.PARTIALLY_FULFILLED

        await self.db.commit()
