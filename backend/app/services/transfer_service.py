"""Transfer Service.

Handles inter-location stock transfers and transfer eligibility checks.
"""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, BusinessRuleError, NotFoundError
from app.models.asset import AssetStatus, SerializedAsset
from app.models.item import Item
from app.models.location import Location
from app.models.transaction import Transaction, TransactionType
from app.models.transfer import Transfer, TransferItem, TransferStatus
from app.services.base_service import BaseService
from app.services.stock_service import StockService
from app.services.asset_service import AssetService


class TransferService(BaseService[Transfer]):
    """Service for transfer management."""

    SERIALIZED_TRANSFER_TYPES = {"equipment", "instrument"}
    
    @property
    def model(self):
        return Transfer
    
    async def get_by_id(self, id: str) -> Optional[Transfer]:
        """Get transfer with related data."""
        result = await self.db.execute(
            select(Transfer)
            .options(
                selectinload(Transfer.from_location),
                selectinload(Transfer.to_location),
                selectinload(Transfer.items).selectinload(TransferItem.item),
                selectinload(Transfer.requested_by),
                selectinload(Transfer.approved_by),
                selectinload(Transfer.assigned_to),
                selectinload(Transfer.destination_responsible),
            )
            .where(Transfer.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_reference(self, transfer_number: str) -> Optional[Transfer]:
        """Get transfer by transfer number."""
        result = await self.db.execute(
            select(Transfer)
            .options(
                selectinload(Transfer.items),
                selectinload(Transfer.assigned_to),
                selectinload(Transfer.destination_responsible),
            )
            .where(Transfer.transfer_number == transfer_number)
        )
        return result.scalar_one_or_none()
    
    async def list_transfers(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        source_location_id: Optional[str] = None,
        destination_location_id: Optional[str] = None,
        status: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        location_ids: Optional[List[str]] = None,
        assigned_to_id: Optional[str] = None,
        requested_by_id: Optional[str] = None,
    ) -> Tuple[List[Transfer], int]:
        """
        List transfers with filtering.
        
        Returns:
            Tuple of (transfers, total_count)
        """
        query = select(Transfer).options(
            selectinload(Transfer.from_location),
            selectinload(Transfer.to_location),
            selectinload(Transfer.items).selectinload(TransferItem.item),
            selectinload(Transfer.requested_by),
            selectinload(Transfer.approved_by),
            selectinload(Transfer.assigned_to),
            selectinload(Transfer.destination_responsible),
        )
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(
                or_(
                    Transfer.from_location_id.in_(location_ids),
                    Transfer.to_location_id.in_(location_ids),
                )
            )
        
        # Apply filters
        if source_location_id:
            query = query.where(Transfer.from_location_id == source_location_id)
        
        if destination_location_id:
            query = query.where(Transfer.to_location_id == destination_location_id)
        
        if status:
            query = query.where(Transfer.status == status)
        
        if assigned_to_id:
            query = query.where(Transfer.assigned_to_id == assigned_to_id)
        
        if requested_by_id:
            query = query.where(Transfer.requested_by_id == requested_by_id)
        
        if start_date:
            query = query.where(Transfer.created_at >= start_date)
        
        if end_date:
            query = query.where(Transfer.created_at <= end_date)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(Transfer, sort_by):
            order_column = getattr(Transfer, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        transfers = list(result.scalars().unique().all())
        
        return transfers, total
    
    def _generate_reference(self) -> str:
        """Generate a transfer reference number."""
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        return f"TRF-{timestamp}"

    async def ensure_dc_number(self, transfer: Transfer) -> str:
        """Return the transfer's stable SS/<year>/<serial> Delivery Challan number."""
        if transfer.dc_number:
            return transfer.dc_number

        number_date = transfer.approved_at or datetime.utcnow()
        year = number_date.year
        prefix = f"SS/{year}/"

        # Serialize annual number allocation on PostgreSQL. SQLite ignores row locks,
        # which is sufficient for local development and isolated tests.
        if self.db.get_bind().dialect.name == "postgresql":
            await self.db.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
                {"lock_key": f"delivery-challan-{year}"},
            )

        existing_result = await self.db.execute(
            select(Transfer.dc_number).where(Transfer.dc_number.like(f"{prefix}%"))
        )
        serials = []
        for number in existing_result.scalars():
            if number:
                suffix = number[len(prefix):]
                if suffix.isdigit():
                    serials.append(int(suffix))

        transfer.dc_number = f"{prefix}{max(serials, default=0) + 1:04d}"
        await self.db.flush()
        return transfer.dc_number

    @staticmethod
    def _get_month_range(now: datetime) -> Tuple[datetime, datetime]:
        """Return first day of current month and first day of next month."""
        month_start = datetime(now.year, now.month, 1)
        if now.month == 12:
            next_month_start = datetime(now.year + 1, 1, 1)
        else:
            next_month_start = datetime(now.year, now.month + 1, 1)
        return month_start, next_month_start

    def _get_asset_blocked_reasons(
        self,
        asset: SerializedAsset,
        today: date,
        month_start: datetime,
        next_month_start: datetime,
    ) -> List[str]:
        """Compute transfer blocked reasons for one asset."""
        reasons: List[str] = []

        # ── Calibration checks ───────────────────────────────────────────────
        if asset.status == AssetStatus.UNDER_CALIBRATION:
            reasons.append("Calibration is pending")
        elif asset.status == AssetStatus.OUT_OF_SERVICE:
            reasons.append("Equipment is out of service")

        if asset.item and asset.item.requires_calibration:
            latest = asset.latest_calibration
            if not latest:
                reasons.append("Calibration is pending")
            else:
                if latest.result and latest.result.lower() != "pass":
                    reasons.append(f"Calibration result is '{latest.result}'")
                if latest.due_at and latest.due_at <= today:
                    if latest.due_at < today:
                        reasons.append(f"Calibration expired on {latest.due_at.isoformat()}")
                    else:
                        reasons.append("Calibration is due today")

        # ── Maintenance checks ───────────────────────────────────────────────
        # Equipment has no periodic maintenance requirement; only assets
        # explicitly marked under maintenance should be blocked from transfer.
        if asset.status == AssetStatus.UNDER_MAINTENANCE:
            reasons.append("Maintenance is pending")

        return list(dict.fromkeys(reasons))

    async def _get_item_transfer_blockers(
        self,
        item_id: str,
        source_location_id: str,
    ) -> List[Dict[str, str]]:
        """Return blocker details for serialized assets of an item at source location."""
        item_result = await self.db.execute(select(Item).where(Item.id == item_id))
        item = item_result.scalar_one_or_none()
        if not item:
            raise NotFoundError(resource="Item", resource_id=item_id)

        if not item.is_serialized:
            return []

        asset_query = (
            select(SerializedAsset)
            .options(
                selectinload(SerializedAsset.item),
                selectinload(SerializedAsset.location),
                selectinload(SerializedAsset.calibration_records),
                selectinload(SerializedAsset.maintenance_records),
            )
            .where(
                and_(
                    SerializedAsset.item_id == item_id,
                    SerializedAsset.location_id == source_location_id,
                )
            )
        )
        asset_result = await self.db.execute(asset_query)
        assets = list(asset_result.scalars().unique().all())

        if not assets:
            return [
                {
                    "item_id": item.id,
                    "item_sku": item.sku,
                    "serial_number": "-",
                    "reason": "No serialized equipment found at source location",
                }
            ]

        now = datetime.utcnow()
        month_start, next_month_start = self._get_month_range(now)
        today = now.date()
        blockers: List[Dict[str, str]] = []

        for asset in assets:
            reasons = self._get_asset_blocked_reasons(asset, today, month_start, next_month_start)
            for reason in reasons:
                blockers.append(
                    {
                        "asset_id": asset.id,
                        "item_id": item.id,
                        "item_sku": item.sku,
                        "serial_number": asset.serial_number,
                        "reason": reason,
                    }
                )

        return blockers

    async def get_equipment_transfer_overview(
        self,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict[str, object]]]:
        """Return equipment transfer eligibility data for UI sections."""
        query = (
            select(SerializedAsset)
            .options(
                selectinload(SerializedAsset.item),
                selectinload(SerializedAsset.location),
                selectinload(SerializedAsset.calibration_records),
                selectinload(SerializedAsset.maintenance_records),
            )
            .join(Item, SerializedAsset.item_id == Item.id)
            .where(
                Item.is_active.is_(True),
                SerializedAsset.status.notin_([
                    AssetStatus.RETIRED,
                    AssetStatus.LOST,
                ]),
            )
        )

        if location_id:
            query = query.where(SerializedAsset.location_id == location_id)

        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))

        result = await self.db.execute(query.order_by(SerializedAsset.serial_number.asc()))
        assets = list(result.scalars().unique().all())

        now = datetime.utcnow()
        month_start, next_month_start = self._get_month_range(now)
        today = now.date()

        items: List[Dict[str, object]] = []
        calibration_issues: List[Dict[str, object]] = []
        maintenance_issues: List[Dict[str, object]] = []

        for asset in assets:
            reasons = self._get_asset_blocked_reasons(asset, today, month_start, next_month_start)
            latest_calibration = asset.latest_calibration
            interval_days = None

            # Past completions only (not future-scheduled)
            past_completions = sorted(
                [r.completed_at.replace(tzinfo=None) for r in asset.maintenance_records
                 if r.completed_at is not None and r.completed_at.replace(tzinfo=None) <= now],
                reverse=True,
            )
            latest_maintenance_completed = past_completions[0] if past_completions else None

            maintenance_next_due_at: Optional[datetime] = None

            # Calibration: flag "due soon" if within CALIBRATION_ALERT_DAYS but not yet expired
            from app.core.config import settings as _settings
            cal_due_soon = False
            if latest_calibration and latest_calibration.due_at:
                days_left = (latest_calibration.due_at - today).days
                if 0 <= days_left <= _settings.CALIBRATION_ALERT_DAYS:
                    cal_due_soon = True

            row: Dict[str, object] = {
                "asset_id": asset.id,
                "item_id": asset.item_id,
                "item_sku": asset.item.sku if asset.item else None,
                "item_name": asset.item.name if asset.item else None,
                "serial_number": asset.serial_number,
                "id_number": asset.item.id_number if asset.item else None,
                "location_id": asset.location_id,
                "location_name": asset.location.name if asset.location else None,
                "maintenance_interval_days": interval_days,
                "calibration_due_at": datetime.combine(latest_calibration.due_at, datetime.min.time()) if latest_calibration and latest_calibration.due_at else None,
                "calibration_result": latest_calibration.result if latest_calibration else None,
                "calibration_due_soon": cal_due_soon,
                "requires_calibration": asset.item.requires_calibration if asset.item else False,
                "maintenance_last_completed_at": latest_maintenance_completed,
                "maintenance_next_due_at": maintenance_next_due_at,
                "maintenance_completed_this_period": not any("Maintenance" in r for r in reasons),
                # kept for backwards compat
                "maintenance_completed_this_month": not any("Maintenance" in r for r in reasons),
                "blocked_reasons": reasons,
                "can_transfer": len(reasons) == 0,
            }
            items.append(row)

            if any("Calibration" in r for r in reasons) or cal_due_soon:
                calibration_issues.append(row)
            if any("Maintenance" in r for r in reasons):
                maintenance_issues.append(row)
        items.sort(key=lambda x: (x["can_transfer"], x["serial_number"]))

        return {
            "items": items,
            "calibration_issues": calibration_issues,
            "maintenance_issues": maintenance_issues,
        }
    
    async def create_transfer(
        self,
        source_location_id: str,
        destination_location_id: str,
        items: List[dict],
        requested_by_id: str,
        notes: Optional[str] = None,
        requires_approval: bool = True,
        transfer_type: str = "consumable",
        required_by_date: Optional[datetime] = None,
        return_date: Optional[datetime] = None,
        purchase_indent_id: Optional[str] = None,
        assigned_to_id: Optional[str] = None,
        destination_responsible_id: Optional[str] = None,
    ) -> Transfer:
        """
        Create a new transfer request.
        
        Args:
            source_location_id: Source location ID
            destination_location_id: Destination location ID
            items: List of items with item_id and quantity
            requested_by_id: User requesting the transfer
            notes: Optional notes
            requires_approval: Whether transfer requires approval
            
        Returns:
            Created transfer
        """
        # Validate locations
        result = await self.db.execute(
            select(Location).where(Location.id == source_location_id)
        )
        source_location = result.scalar_one_or_none()
        if not source_location:
            raise NotFoundError(resource="Source Location", resource_id=source_location_id)
        if not source_location.is_active:
            raise BadRequestError(message="Source location is inactive")
        
        result = await self.db.execute(
            select(Location).where(Location.id == destination_location_id)
        )
        destination_location = result.scalar_one_or_none()
        if not destination_location:
            raise NotFoundError(resource="Destination Location", resource_id=destination_location_id)
        if not destination_location.is_active:
            raise BadRequestError(message="Destination location is inactive")
        
        if source_location_id == destination_location_id and not destination_responsible_id:
            raise BadRequestError(
                message="Select a destination responsible person for same-location local transfers"
            )
        
        # Purchase Indent linkage — auto-create if none provided
        indent_number: Optional[str] = None
        if purchase_indent_id:
            from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus  # avoid circular import
            pi_result = await self.db.execute(
                select(PurchaseIndent).where(PurchaseIndent.id == purchase_indent_id)
            )
            pi = pi_result.scalar_one_or_none()
            if not pi:
                raise NotFoundError(resource="PurchaseIndent", resource_id=purchase_indent_id)
            if pi.status not in (
                PurchaseIndentStatus.APPROVED,
                PurchaseIndentStatus.PARTIALLY_FULFILLED,
            ):
                raise BadRequestError(
                    message=(
                        f"Purchase Indent '{pi.indent_number}' must be in Approved status "
                        f"before a transfer can be created (current status: {pi.status})."
                    )
                )
            indent_number = pi.indent_number
        # else: PI will be auto-created after the transfer is persisted
        stock_service = StockService(self.db)
        transfer_items = []
        compliance_blockers: List[Dict[str, str]] = []
        
        for item_data in items:
            item_id = item_data.get("item_id")
            quantity = Decimal(str(item_data.get("quantity", 0)))
            
            if quantity <= 0:
                raise BadRequestError(message="Transfer quantity must be positive")
            
            # Validate item
            result = await self.db.execute(select(Item).where(Item.id == item_id))
            item = result.scalar_one_or_none()
            if not item:
                raise NotFoundError(resource="Item", resource_id=item_id)

            transfer_is_serialized = transfer_type in self.SERIALIZED_TRANSFER_TYPES
            if transfer_is_serialized and not item.is_serialized:
                raise BadRequestError(
                    message=f"{transfer_type.title()} transfers allow only serial-number tracked items"
                )
            if not transfer_is_serialized and item.is_serialized:
                raise BadRequestError(
                    message=f"{transfer_type.title()} transfers allow only quantity-based items"
                )
            if item.is_serialized and quantity != 1:
                raise BadRequestError(
                    message=f"Serialized item {item.sku} must be transferred one unit per serial number"
                )

            if transfer_is_serialized:
                serial_numbers = item_data.get("serial_numbers") or []
                if len(serial_numbers) != int(quantity):
                    raise BadRequestError(
                        message="Select exactly one source serial number for each serialized transfer line."
                    )
                asset_service = AssetService(self.db)
                for serial_number in serial_numbers:
                    asset = await asset_service.get_by_serial_number(serial_number)
                    if (
                        not asset
                        or asset.item_id != item_id
                        or asset.location_id != source_location_id
                    ):
                        raise BadRequestError(
                            message=f"Serialized asset {serial_number} is not available at the source location."
                        )
                    if await asset_service.has_active_transfer(asset):
                        raise BadRequestError(
                            message=f"Serialized asset {serial_number} is already in an active transfer."
                        )

            # Transfer eligibility checks for serialized equipment
            blockers = await self._get_item_transfer_blockers(item_id, source_location_id)
            compliance_blockers.extend(blockers)
            
            # Check stock availability
            stock = await stock_service.get_stock(item_id, source_location_id)
            if not stock:
                raise BadRequestError(
                    message=f"Item {item.sku} has no stock at source location"
                )
            
            available = stock.quantity_on_hand - stock.quantity_reserved
            if quantity > available:
                raise BadRequestError(
                    message=f"Insufficient stock for {item.sku}. Available: {available}, Requested: {quantity}"
                )
            
            transfer_items.append({
                "item_id": item_id,
                "quantity": int(quantity),
                "lot_number": item_data.get("lot_number"),
                "serial_numbers": item_data.get("serial_numbers"),
                "notes": item_data.get("notes"),
                "item": item,
            })

        if compliance_blockers:
            summary = "; ".join(
                f"{b['item_sku']} [{b['serial_number']}]: {b['reason']}"
                for b in compliance_blockers[:5]
            )
            raise BusinessRuleError(
                message=f"Transfer not allowed due to calibration/maintenance compliance: {summary}",
                rule_code="TRANSFER_BLOCKED_COMPLIANCE",
                details={"blocked_assets": compliance_blockers},
            )
        
        # Create transfer
        initial_status = TransferStatus.REQUESTED if requires_approval else TransferStatus.APPROVED
        
        transfer = Transfer(
            id=self.generate_id(),
            transfer_number=self._generate_reference(),
            from_location_id=source_location_id,
            to_location_id=destination_location_id,
            status=initial_status,
            requested_by_id=requested_by_id,
            assigned_to_id=assigned_to_id,
            destination_responsible_id=destination_responsible_id,
            request_notes=notes,
            requested_date=datetime.utcnow(),
            transfer_type=transfer_type,
            required_by_date=required_by_date,
            return_date=return_date,
            purchase_indent_id=purchase_indent_id,
            purchase_indent_number=indent_number,
        )
        
        self.db.add(transfer)
        await self.db.flush()
        
        # Create transfer items and reserve stock
        for item_data in sorted(transfer_items, key=lambda value: value["item_id"]):
            transfer_item = TransferItem(
                id=self.generate_id(),
                transfer_id=transfer.id,
                item_id=item_data["item_id"],
                quantity_requested=item_data["quantity"],
                quantity_shipped=0,
                quantity_received=0,
                lot_number=item_data["lot_number"],
                serial_numbers=json.dumps(item_data["serial_numbers"]) if item_data["serial_numbers"] else None,
                notes=item_data["notes"],
            )
            self.db.add(transfer_item)
            
            # Reserve stock
            await stock_service.reserve_stock(
                item_id=item_data["item_id"],
                location_id=source_location_id,
                quantity=Decimal(str(item_data["quantity"])),
                commit=False,
            )
        
        # Auto-create Purchase Indent if none was provided
        if not purchase_indent_id:
            from app.models.purchase_indent import PurchaseIndent, PurchaseIndentItem, PurchaseIndentStatus
            from app.services.purchase_indent_service import PurchaseIndentService

            auto_indent_number = await PurchaseIndentService(self.db).generate_indent_number(
                destination_location_id
            )
            auto_pi = PurchaseIndent(
                id=self.generate_id(),
                indent_number=auto_indent_number,
                requested_by_location_id=destination_location_id,
                supplying_location_id=source_location_id,
                requested_by_id=requested_by_id,
                indent_date=datetime.utcnow(),
                required_by_date=required_by_date,
                purpose=f"Auto-created for Transfer {transfer.transfer_number}",
                notes=notes,
                status=PurchaseIndentStatus.SUBMITTED,
            )
            self.db.add(auto_pi)
            await self.db.flush()

            for item_data in transfer_items:
                pi_line = PurchaseIndentItem(
                    id=self.generate_id(),
                    indent_id=auto_pi.id,
                    item_id=item_data["item_id"],
                    quantity_requested=item_data["quantity"],
                    quantity_approved=0,
                    quantity_fulfilled=0,
                )
                self.db.add(pi_line)

            # Link the PI back to the transfer
            transfer.purchase_indent_id = auto_pi.id
            transfer.purchase_indent_number = auto_indent_number

        await self.db.commit()

        # Re-fetch with all relationships for response serialization
        return await self.get_by_id(transfer.id)
    
    async def approve_transfer(
        self,
        transfer_id: str,
        approved: bool,
        notes: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        user_id: Optional[str] = None,
        allow_self_approval: bool = False,
    ) -> Transfer:
        """Approve or reject a pending transfer."""
        transfer = await self.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)
        
        if transfer.status != TransferStatus.REQUESTED:
            raise BadRequestError(
                message=f"Cannot approve transfer with status '{transfer.status}'"
            )

        # Prevent self-approval unless a higher authority explicitly allows it.
        if approved and user_id and transfer.requested_by_id == user_id and not allow_self_approval:
            raise BadRequestError(
                message="You cannot approve your own transfer request"
            )

        if approved:
            # Recheck compliance before final approval
            compliance_blockers: List[Dict[str, str]] = []
            for item in transfer.items:
                compliance_blockers.extend(
                    await self._get_item_transfer_blockers(item.item_id, transfer.from_location_id)
                )

            if compliance_blockers:
                summary = "; ".join(
                    f"{b['item_sku']} [{b['serial_number']}]: {b['reason']}"
                    for b in compliance_blockers[:5]
                )
                raise BusinessRuleError(
                    message=f"Transfer cannot be approved because compliance is pending: {summary}",
                    rule_code="TRANSFER_BLOCKED_COMPLIANCE",
                    details={"blocked_assets": compliance_blockers},
                )

            transfer.status = TransferStatus.APPROVED
            transfer.approved_by_id = user_id
            transfer.approved_at = datetime.utcnow()
            await self.ensure_dc_number(transfer)
            if notes:
                transfer.approval_notes = notes

            # Auto-approve the linked Purchase Indent when transfer is approved
            if transfer.purchase_indent_id:
                from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus
                pi_result = await self.db.execute(
                    select(PurchaseIndent)
                    .options(selectinload(PurchaseIndent.items))
                    .where(PurchaseIndent.id == transfer.purchase_indent_id)
                )
                pi = pi_result.scalar_one_or_none()
                if pi and pi.status == PurchaseIndentStatus.SUBMITTED:
                    pi.status = PurchaseIndentStatus.APPROVED
                    pi.approved_by_id = user_id
                    pi.approved_at = datetime.utcnow()
                    # Set approved quantities equal to requested
                    for line in pi.items:
                        line.quantity_approved = line.quantity_requested
        else:
            stock_service = StockService(self.db)
            for item in transfer.items:
                await stock_service.release_reservation(
                    item_id=item.item_id,
                    location_id=transfer.from_location_id,
                    quantity=Decimal(str(item.quantity_requested)),
                )
            transfer.status = TransferStatus.REJECTED
            transfer.rejection_reason = rejection_reason or notes
            if notes:
                transfer.approval_notes = notes
        
        await self.db.commit()
        await self.db.refresh(transfer)
        
        return transfer
    
    async def reject_transfer(
        self,
        transfer_id: str,
        rejected_by_id: str,
        reason: str,
    ) -> Transfer:
        """Backward-compatible reject helper."""
        return await self.approve_transfer(
            transfer_id=transfer_id,
            approved=False,
            notes=reason,
            rejection_reason=reason,
            user_id=rejected_by_id,
        )
    
    async def ship_transfer(
        self,
        transfer_id: str,
        request,
        user_id: Optional[str] = None,
    ) -> Transfer:
        """Ship an approved transfer."""
        transfer = await self.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)
        
        if transfer.status not in (
            TransferStatus.APPROVED,
            TransferStatus.IN_TRANSIT,
            TransferStatus.PARTIALLY_RECEIVED,
        ):
            raise BadRequestError(
                message=f"Cannot ship transfer with status '{transfer.status}'"
            )

        # Re-validate compliance at shipment time (calibration may have expired since approval)
        if transfer.transfer_type in self.SERIALIZED_TRANSFER_TYPES:
            compliance_blockers: List[Dict[str, str]] = []
            for item in transfer.items:
                compliance_blockers.extend(
                    await self._get_item_transfer_blockers(item.item_id, transfer.from_location_id)
                )
            if compliance_blockers:
                summary = "; ".join(
                    f"{b['item_sku']} [{b['serial_number']}]: {b['reason']}"
                    for b in compliance_blockers[:5]
                )
                raise BusinessRuleError(
                    message=f"Shipment blocked: calibration/maintenance compliance failed: {summary}",
                    rule_code="TRANSFER_BLOCKED_COMPLIANCE",
                    details={"blocked_assets": compliance_blockers},
                )

        stock_service = StockService(self.db)
        shipped_map = {}
        if request.shipped_items:
            shipped_map = {
                item.transfer_item_id: int(item.quantity_shipped)
                for item in request.shipped_items
            }
        low_stock_checks = []
        
        shipped_this_operation = 0
        for item in transfer.items:
            remaining_to_ship = item.quantity_requested - item.quantity_shipped
            shipped_qty = remaining_to_ship
            if item.id in shipped_map:
                shipped_qty = shipped_map[item.id]
            if shipped_qty < 0 or shipped_qty > remaining_to_ship:
                raise BadRequestError(
                    message=f"Invalid shipped quantity for transfer item {item.id}. Remaining: {remaining_to_ship}"
                )
            
            # Update stock
            stock = await stock_service.get_stock_for_update(
                item.item_id,
                transfer.from_location_id,
            )
            if not stock:
                raise NotFoundError(resource="Stock", resource_id=f"{item.item_id}@{transfer.from_location_id}")

            if stock.quantity_on_hand < Decimal(str(shipped_qty)):
                raise BadRequestError(
                    message=f"Insufficient stock to ship item {item.item_id}"
                )

            stock.quantity_on_hand -= shipped_qty
            stock.quantity_reserved -= shipped_qty
            if shipped_qty > 0:
                low_stock_checks.append(stock)
            
            item.quantity_shipped += shipped_qty
            shipped_this_operation += shipped_qty

            if shipped_qty > 0:
                self.db.add(
                    Transaction(
                        id=self.generate_id(),
                        transaction_type=TransactionType.TRANSFER_OUT,
                        item_id=item.item_id,
                        location_id=transfer.from_location_id,
                        quantity=shipped_qty,
                        reference_type="transfer",
                        reference_id=transfer.id,
                        reference_number=transfer.transfer_number,
                        reason="Transfer shipment",
                        notes=request.notes,
                        created_by_id=user_id,
                        transaction_date=datetime.utcnow(),
                    )
                )
        
        if shipped_this_operation <= 0:
            raise BadRequestError(message="At least one remaining unit must be shipped")
        transfer.status = (
            TransferStatus.PARTIALLY_RECEIVED
            if any(item.quantity_received > 0 for item in transfer.items)
            else TransferStatus.IN_TRANSIT
        )
        transfer.shipped_by_id = user_id
        transfer.shipped_at = datetime.utcnow()
        transfer.shipping_method = request.shipping_method
        transfer.tracking_number = request.tracking_number
        transfer.shipping_notes = request.notes
        
        await self.db.commit()
        await self.db.refresh(transfer)

        for stock in low_stock_checks:
            await stock_service._check_and_send_low_stock_alert(stock, action="transfer shipment")
        
        return transfer
    
    async def receive_transfer(
        self,
        transfer_id: str,
        request,
        user_id: Optional[str] = None,
    ) -> Transfer:
        """Receive a shipped transfer."""
        transfer = await self.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)
        
        if transfer.status not in (
            TransferStatus.IN_TRANSIT,
            TransferStatus.PARTIALLY_RECEIVED,
        ):
            raise BadRequestError(
                message=f"Cannot receive transfer with status '{transfer.status}'"
            )

        if (
            transfer.from_location_id == transfer.to_location_id
            and (transfer.shipping_method or "").lower() == "issue stock"
        ):
            raise BadRequestError(
                message="Local issue stock transfers are completed at issue time and cannot be received"
            )
        
        stock_service = StockService(self.db)
        received_map = {
            detail.transfer_item_id: detail for detail in request.received_items
        }
        accounted_this_operation = 0
        
        for item in transfer.items:
            remaining_to_receive = (
                item.quantity_shipped
                - item.quantity_received
                - item.quantity_damaged
                - item.quantity_lost
            )
            received_qty = remaining_to_receive
            damaged_qty = 0
            lost_qty = 0
            detail = received_map.get(item.id)
            if detail:
                received_qty = int(detail.quantity_received)
                damaged_qty = int(detail.quantity_damaged)
                lost_qty = int(detail.quantity_lost)

            accounted_qty = received_qty + damaged_qty + lost_qty
            if accounted_qty < 0 or accounted_qty > remaining_to_receive:
                raise BadRequestError(
                    message=(
                        f"Invalid receipt disposition for transfer item {item.id}. "
                        f"Remaining shipped quantity: {remaining_to_receive}"
                    )
                )
            
            # Add to destination stock
            if received_qty > 0:
                stock = await stock_service.get_or_create_stock_for_update(
                    item.item_id,
                    transfer.to_location_id,
                )
                stock.quantity_on_hand += received_qty
            
            item.quantity_received += received_qty
            item.quantity_damaged += damaged_qty
            item.quantity_lost += lost_qty
            accounted_this_operation += accounted_qty
            if detail and detail.condition_notes:
                disposition = (
                    f"Item {item.item_id}: received={received_qty}, "
                    f"damaged={damaged_qty}, lost={lost_qty}. "
                    f"{detail.condition_notes.strip()}"
                )
                request.notes = (
                    f"{request.notes.strip()}\n{disposition}"
                    if request.notes and request.notes.strip() else disposition
                )

            if received_qty > 0:
                self.db.add(
                    Transaction(
                        id=self.generate_id(),
                        transaction_type=TransactionType.TRANSFER_IN,
                        item_id=item.item_id,
                        location_id=transfer.to_location_id,
                        quantity=received_qty,
                        reference_type="transfer",
                        reference_id=transfer.id,
                        reference_number=transfer.transfer_number,
                        reason="Transfer receipt",
                        notes=request.notes,
                        created_by_id=user_id or transfer.requested_by_id,
                        transaction_date=datetime.utcnow(),
                    )
                )

            # For serialized transfers, update the SerializedAsset's tracked location.
            if transfer.transfer_type in self.SERIALIZED_TRANSFER_TYPES and received_qty > 0:
                asset_result = await self.db.execute(
                    select(SerializedAsset)
                    .where(
                        SerializedAsset.item_id == item.item_id,
                        SerializedAsset.location_id == transfer.from_location_id,
                    )
                    .limit(int(received_qty))
                )
                assets_to_move = list(asset_result.scalars().all())
                for asset in assets_to_move:
                    asset.location_id = transfer.to_location_id
        
        if accounted_this_operation <= 0:
            raise BadRequestError(
                message="At least one shipped unit must be received or recorded as damaged/lost"
            )
        transfer.status = (
            TransferStatus.RECEIVED
            if all(
                item.quantity_received + item.quantity_damaged + item.quantity_lost
                == item.quantity_requested
                for item in transfer.items
            )
            else TransferStatus.PARTIALLY_RECEIVED
        )
        transfer.received_by_id = user_id
        transfer.received_at = datetime.utcnow()
        transfer.receiving_notes = request.notes
        
        await self.db.commit()
        await self.db.refresh(transfer)
        
        return transfer
    
    async def cancel_transfer(
        self,
        transfer_id: str,
        user_id: Optional[str] = None,
    ) -> Transfer:
        """Cancel a transfer."""
        transfer = await self.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)
        
        if transfer.status in [
            TransferStatus.RECEIVED,
            TransferStatus.CANCELLED,
            TransferStatus.PARTIALLY_RECEIVED,
        ]:
            raise BadRequestError(
                message=f"Cannot cancel transfer with status '{transfer.status}'"
            )
        
        stock_service = StockService(self.db)
        if transfer.status in [TransferStatus.REQUESTED, TransferStatus.APPROVED]:
            # Release reserved stock
            for item in transfer.items:
                await stock_service.release_reservation(
                    item_id=item.item_id,
                    location_id=transfer.from_location_id,
                    quantity=Decimal(str(item.quantity_requested)),
                )
        elif transfer.status == TransferStatus.IN_TRANSIT:
            # Stock was already deducted at shipment; restore it at source location
            for item in transfer.items:
                source_stock = await stock_service.get_or_create_stock_for_update(
                    item.item_id, transfer.from_location_id
                )
                source_stock.quantity_on_hand += item.quantity_shipped
                source_stock.quantity_reserved -= (
                    item.quantity_requested - item.quantity_shipped
                )
        
        transfer.status = TransferStatus.CANCELLED

        if transfer.purchase_indent_id:
            from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus

            linked_statuses = list((await self.db.execute(
                select(Transfer.status).where(
                    Transfer.purchase_indent_id == transfer.purchase_indent_id
                )
            )).scalars().all())
            if linked_statuses and all(
                status in (TransferStatus.CANCELLED, TransferStatus.REJECTED)
                for status in linked_statuses
            ):
                indent = await self.db.get(PurchaseIndent, transfer.purchase_indent_id)
                if indent and indent.status not in (
                    PurchaseIndentStatus.FULFILLED,
                    PurchaseIndentStatus.PARTIALLY_FULFILLED,
                ):
                    indent.status = PurchaseIndentStatus.CANCELLED
        
        await self.db.commit()
        await self.db.refresh(transfer)
        
        return transfer

    async def update_return_date(
        self,
        transfer_id: str,
        return_date: "datetime",
        reason: str,
        return_reminder_days: int | None = None,
    ) -> Transfer:
        """Update the return date for an equipment transfer."""
        transfer = await self.get_by_id(transfer_id)
        if not transfer:
            raise NotFoundError(resource="Transfer", resource_id=transfer_id)

        transfer.return_date = return_date
        transfer.return_date_modified_reason = reason
        if return_reminder_days is not None:
            transfer.return_reminder_days = return_reminder_days

        await self.db.commit()
        await self.db.refresh(transfer)

        return transfer
