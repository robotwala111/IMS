"""
Transaction Service

Handles inventory transactions (receipts, issues, returns, adjustments).
"""

from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.transaction import Transaction, TransactionType
from app.models.item import Item
from app.models.location import Location
from app.models.stock import StockLot
from app.services.base_service import BaseService
from app.services.stock_service import StockService


class TransactionService(BaseService[Transaction]):
    """Service for transaction management."""
    
    @property
    def model(self):
        return Transaction
    
    async def get_by_id(self, id: str) -> Optional[Transaction]:
        """Get transaction with related data."""
        result = await self.db.execute(
            select(Transaction)
            .options(
                selectinload(Transaction.item),
                selectinload(Transaction.location),
                selectinload(Transaction.created_by),
            )
            .where(Transaction.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_reference(self, reference_number: str) -> Optional[Transaction]:
        """Get transaction by reference number."""
        result = await self.db.execute(
            select(Transaction)
            .options(
                selectinload(Transaction.item),
                selectinload(Transaction.location),
            )
            .where(Transaction.reference_number == reference_number)
        )
        return result.scalar_one_or_none()
    
    async def list_transactions(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        location_id: Optional[str] = None,
        item_id: Optional[str] = None,
        transaction_type: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        location_ids: Optional[List[str]] = None,
        filters=None,
    ) -> Tuple[List[Transaction], int]:
        """
        List transactions with filtering.
        
        Returns:
            Tuple of (transactions, total_count)
        """
        # Unpack filters object if provided (from endpoint)
        if filters is not None:
            location_id = getattr(filters, 'location_id', None) or location_id
            item_id = getattr(filters, 'item_id', None) or item_id
            transaction_type = getattr(filters, 'transaction_type', None) or transaction_type
            start_date = getattr(filters, 'date_from', None) or start_date
            end_date = getattr(filters, 'date_to', None) or end_date

        query = select(Transaction).options(
            selectinload(Transaction.item),
            selectinload(Transaction.location),
            selectinload(Transaction.created_by),
        )
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(Transaction.location_id.in_(location_ids))
        
        # Apply filters
        if location_id:
            query = query.where(Transaction.location_id == location_id)
        
        if item_id:
            query = query.where(Transaction.item_id == item_id)
        
        if transaction_type:
            query = query.where(Transaction.transaction_type == transaction_type)
        
        if start_date:
            query = query.where(Transaction.created_at >= start_date)
        
        if end_date:
            query = query.where(Transaction.created_at <= end_date)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(Transaction, sort_by):
            order_column = getattr(Transaction, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        transactions = list(result.scalars().unique().all())
        
        return transactions, total
    
    def _generate_reference(self, prefix: str) -> str:
        """Generate a reference number."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"{prefix}-{timestamp}"
    
    async def process_receipt(
        self,
        request,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Process a multi-line receipt request.
        
        Args:
            request: ReceiptRequest schema with line_items
            user_id: User performing the receipt
            
        Returns:
            Dict with transaction_ids and summary
        """
        stock_service = StockService(self.db)
        transaction_ids = []
        ref = request.reference_number or self._generate_reference("RCV")
        
        for line in request.line_items:
            # Validate item
            from app.models.category import Category

            result = await self.db.execute(
                select(Item)
                .options(selectinload(Item.category).selectinload(Category.category_type))
                .where(Item.id == line.item_id)
            )
            item = result.scalar_one_or_none()
            if not item:
                raise NotFoundError(resource="Item", resource_id=line.item_id)
            if item.is_serialized:
                raise BadRequestError(
                    message="Serialized products must use product asset workflows, not quantity stock receipt."
                )
            if (item.stock_behavior == "serialized" or item.is_serialized) and line.quantity != 1:
                raise BadRequestError(
                    message="Equipment and instruments are serialized; receive one serial-numbered item at a time."
                )
            
            # Update stock
            stock = await stock_service.get_or_create_stock_for_update(line.item_id, request.location_id)
            stock.quantity_on_hand += line.quantity
            
            # Create lot if tracking
            if line.lot_number or item.has_expiry:
                await stock_service.create_lot(
                    item_id=line.item_id,
                    location_id=request.location_id,
                    lot_number=line.lot_number or self._generate_reference("LOT"),
                    quantity=line.quantity,
                    expiry_date=line.expiry_date,
                    supplier=request.supplier,
                    cost_per_unit=line.unit_cost,
                )
            
            # Create transaction
            notes_parts = []
            if request.supplier:
                notes_parts.append(f"Supplier: {request.supplier}")
            if request.notes:
                notes_parts.append(request.notes)
            notes = "\n".join(notes_parts) or None

            txn = Transaction(
                id=self.generate_id(),
                reference_number=ref,
                transaction_type=TransactionType.RECEIPT,
                item_id=line.item_id,
                location_id=request.location_id,
                quantity=line.quantity,
                unit_cost=line.unit_cost,
                total_cost=line.unit_cost * line.quantity if line.unit_cost else None,
                reason=notes,
                notes=notes,
                created_by_id=user_id,
                transaction_date=request.received_date or datetime.now(timezone.utc),
            )
            self.db.add(txn)
            transaction_ids.append(txn.id)
        
        await self.db.commit()
        
        return {
            "transaction_ids": transaction_ids,
            "reference_number": ref,
            "line_count": len(request.line_items),
        }
    
    async def process_issue(
        self,
        request,
        user_id: str,
        is_admin: bool = False,
    ) -> Dict[str, Any]:
        """
        Process a multi-line issue request.
        
        Args:
            request: IssueRequest schema with line_items
            user_id: User performing the issue
            is_admin: Whether user is admin (for override)
            
        Returns:
            Dict with transaction_ids and summary
        """
        stock_service = StockService(self.db)
        transaction_ids = []
        ref = request.reference_number or self._generate_reference("ISS")
        
        for line in request.line_items:
            # Validate item
            result = await self.db.execute(select(Item).where(Item.id == line.item_id))
            item = result.scalar_one_or_none()
            if not item:
                raise NotFoundError(resource="Item", resource_id=line.item_id)
            if item.is_serialized:
                raise BadRequestError(
                    message="Serialized products must use product asset workflows, not quantity stock issue."
                )
            
            # Check stock
            stock = await stock_service.get_stock_for_update(line.item_id, request.location_id)
            if not stock:
                raise BadRequestError(
                    message=f"No stock for item '{item.name}' at this location"
                )
            
            available = stock.quantity_on_hand - stock.quantity_reserved
            if line.quantity > available:
                raise BadRequestError(
                    message=f"Insufficient stock for '{item.name}'. Available: {available}, Requested: {line.quantity}"
                )
            
            # Allocate lot-controlled stock using FEFO. An explicit lot remains
            # supported, but expired lots can never be issued as usable stock.
            allocations: List[Tuple[Optional[StockLot], int]] = []
            if item.has_expiry or item.is_lot_tracked or line.lot_id:
                lot_query = (
                    select(StockLot)
                    .where(
                        StockLot.item_id == line.item_id,
                        StockLot.location_id == request.location_id,
                        StockLot.quantity_on_hand > StockLot.quantity_reserved,
                    )
                    .order_by(
                        StockLot.expiry_date.asc().nullslast(),
                        StockLot.received_at.asc(),
                        StockLot.id.asc(),
                    )
                    .with_for_update()
                )
                if line.lot_id:
                    lot_query = lot_query.where(StockLot.id == line.lot_id)
                lots = list((await self.db.execute(lot_query)).scalars().all())
                remaining = line.quantity
                today = datetime.now(timezone.utc).date()
                for lot in lots:
                    if lot.expiry_date and lot.expiry_date < today:
                        if line.lot_id:
                            raise BadRequestError(
                                message=f"Lot '{lot.lot_number}' expired on {lot.expiry_date}"
                            )
                        continue
                    available_in_lot = lot.quantity_on_hand - lot.quantity_reserved
                    allocated = min(remaining, available_in_lot)
                    if allocated > 0:
                        allocations.append((lot, allocated))
                        remaining -= allocated
                    if remaining == 0:
                        break
                if remaining:
                    raise BadRequestError(
                        message=(
                            f"Insufficient non-expired lot stock for '{item.name}'. "
                            f"Available: {line.quantity - remaining}, Requested: {line.quantity}"
                        )
                    )
            else:
                allocations.append((None, line.quantity))

            stock.quantity_on_hand -= line.quantity
            for lot, allocated in allocations:
                if lot:
                    lot.quantity_on_hand -= allocated

            notes_parts = []
            if request.issued_to:
                notes_parts.append(f"Issued to: {request.issued_to}")
            if request.reason:
                notes_parts.append(f"Reason: {request.reason}")
            if line.notes:
                notes_parts.append(line.notes)
            
            for lot, allocated in allocations:
                txn = Transaction(
                    id=self.generate_id(),
                    reference_number=ref,
                    transaction_type=TransactionType.ISSUE,
                    item_id=line.item_id,
                    location_id=request.location_id,
                    quantity=allocated,
                    lot_id=lot.id if lot else None,
                    reason=request.reason,
                    notes=". ".join(notes_parts) if notes_parts else None,
                    created_by_id=user_id,
                    transaction_date=datetime.now(timezone.utc),
                )
                self.db.add(txn)
                transaction_ids.append(txn.id)
        
        await self.db.commit()
        
        return {
            "transaction_ids": transaction_ids,
            "reference_number": ref,
            "line_count": len(request.line_items),
        }
    
    async def process_return(
        self,
        request,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Process a multi-line return request.
        
        Args:
            request: ReturnRequest schema with line_items
            user_id: User performing the return
            
        Returns:
            Dict with transaction_ids and summary
        """
        stock_service = StockService(self.db)
        transaction_ids = []
        ref = request.reference_number or self._generate_reference("RTN")

        if request.idempotency_key:
            existing_result = await self.db.execute(
                select(Transaction)
                .where(
                    Transaction.transaction_type == TransactionType.RETURN,
                    Transaction.idempotency_key == request.idempotency_key,
                )
                .order_by(Transaction.idempotency_line)
            )
            existing = list(existing_result.scalars().all())
            if existing:
                same_request = len(existing) == len(request.line_items) and all(
                    txn.item_id == line.item_id
                    and txn.location_id == request.location_id
                    and txn.quantity == line.quantity
                    and txn.reference_id == line.original_issue_id
                    and (txn.return_condition or "good") == (line.condition or "good")
                    for txn, line in zip(existing, request.line_items)
                )
                if not same_request:
                    raise BadRequestError(message="Idempotency key was already used for a different return")
                return {
                    "transaction_ids": [txn.id for txn in existing],
                    "reference_number": existing[0].reference_number,
                    "line_count": len(existing),
                    "idempotent_replay": True,
                }
        
        for line_number, line in enumerate(request.line_items):
            # Validate item
            result = await self.db.execute(select(Item).where(Item.id == line.item_id))
            item = result.scalar_one_or_none()
            if not item:
                raise NotFoundError(resource="Item", resource_id=line.item_id)
            if item.is_serialized:
                raise BadRequestError(
                    message="Serialized products must use product asset workflows, not quantity stock return."
                )

            issue_result = await self.db.execute(
                select(Transaction)
                .where(Transaction.id == line.original_issue_id)
                .with_for_update()
            )
            original_issue = issue_result.scalar_one_or_none()
            if not original_issue or original_issue.transaction_type != TransactionType.ISSUE:
                raise BadRequestError(message="Return must reference an existing stock issue")
            if original_issue.item_id != line.item_id or original_issue.location_id != request.location_id:
                raise BadRequestError(message="Returned item and location must match the original issue")

            # A concurrent request can pass the initial replay check before this
            # issue-row lock becomes available. Recheck after acquiring the lock.
            if line_number == 0 and request.idempotency_key:
                replay_result = await self.db.execute(
                    select(Transaction)
                    .where(
                        Transaction.transaction_type == TransactionType.RETURN,
                        Transaction.idempotency_key == request.idempotency_key,
                    )
                    .order_by(Transaction.idempotency_line)
                )
                replay = list(replay_result.scalars().all())
                if replay:
                    same_request = len(replay) == len(request.line_items) and all(
                        txn.item_id == replay_line.item_id
                        and txn.location_id == request.location_id
                        and txn.quantity == replay_line.quantity
                        and txn.reference_id == replay_line.original_issue_id
                        and (txn.return_condition or "good") == (replay_line.condition or "good")
                        for txn, replay_line in zip(replay, request.line_items)
                    )
                    if not same_request:
                        raise BadRequestError(
                            message="Idempotency key was already used for a different return"
                        )
                    return {
                        "transaction_ids": [txn.id for txn in replay],
                        "reference_number": replay[0].reference_number,
                        "line_count": len(replay),
                        "idempotent_replay": True,
                    }

            returned_result = await self.db.execute(
                select(func.coalesce(func.sum(Transaction.quantity), 0)).where(
                    Transaction.transaction_type == TransactionType.RETURN,
                    Transaction.reference_type == "transaction",
                    Transaction.reference_id == original_issue.id,
                )
            )
            already_returned = int(returned_result.scalar_one())
            returnable = original_issue.quantity - already_returned
            if line.quantity > returnable:
                raise BadRequestError(
                    message=(
                        "Return quantity exceeds the remaining issued quantity. "
                        f"Returnable: {returnable}, Requested: {line.quantity}"
                    )
                )
            
            condition = (line.condition or "good").lower()
            if line.lot_id and line.lot_id != original_issue.lot_id:
                raise BadRequestError(message="Returned lot must match the original issued lot")

            # Only serviceable returns re-enter available inventory. Damaged and
            # expired goods remain traceable but quarantined from usable stock.
            if condition == "good":
                stock = await stock_service.get_or_create_stock_for_update(
                    line.item_id, request.location_id
                )
                stock.quantity_on_hand += line.quantity
                if original_issue.lot_id:
                    lot_result = await self.db.execute(
                        select(StockLot)
                        .where(StockLot.id == original_issue.lot_id)
                        .with_for_update()
                    )
                    original_lot = lot_result.scalar_one_or_none()
                    if not original_lot:
                        raise BadRequestError(message="Original issued lot no longer exists")
                    if original_lot.expiry_date and original_lot.expiry_date < datetime.now(timezone.utc).date():
                        raise BadRequestError(
                            message="An expired lot cannot be returned to usable stock; mark it expired"
                        )
                    original_lot.quantity_on_hand += line.quantity
            
            notes_parts = []
            if request.returned_by:
                notes_parts.append(f"Returned by: {request.returned_by}")
            if line.condition and line.condition != "good":
                notes_parts.append(f"Condition: {line.condition}")
            if line.notes:
                notes_parts.append(line.notes)
            
            txn = Transaction(
                id=self.generate_id(),
                reference_number=ref,
                transaction_type=TransactionType.RETURN,
                item_id=line.item_id,
                location_id=request.location_id,
                quantity=line.quantity,
                reference_type="transaction",
                reference_id=original_issue.id,
                lot_id=original_issue.lot_id,
                idempotency_key=request.idempotency_key,
                idempotency_line=line_number if request.idempotency_key else None,
                return_condition=condition,
                reason=request.reason,
                notes=". ".join(notes_parts) if notes_parts else None,
                created_by_id=user_id,
                transaction_date=datetime.now(timezone.utc),
            )
            self.db.add(txn)
            transaction_ids.append(txn.id)
        
        await self.db.commit()
        
        return {
            "transaction_ids": transaction_ids,
            "reference_number": ref,
            "line_count": len(request.line_items),
        }
