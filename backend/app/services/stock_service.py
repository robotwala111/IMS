"""
Stock Service

Handles stock level management and queries.
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple
import asyncio

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.stock import Stock, StockLot
from app.models.item import Item
from app.models.category import Category
from app.models.location import Location
from app.models.transaction import Transaction, TransactionType
from app.services.base_service import BaseService

logger = get_logger(__name__)


class StockService(BaseService[Stock]):
    """Service for stock management."""
    
    @property
    def model(self):
        return Stock

    async def get_by_id(self, id: str) -> Optional[Stock]:
        """Get stock with item and location loaded for API serialization."""
        result = await self.db.execute(
            select(Stock)
            .options(
                selectinload(Stock.item),
                selectinload(Stock.location),
            )
            .where(Stock.id == id)
        )
        return result.scalar_one_or_none()
    
    async def _check_and_send_low_stock_alert(
        self,
        stock: Stock,
        action: str = "operation"
    ) -> None:
        """
        Check if stock is below minimum level and send instant email alert.
        Recipients:
          - Location managers assigned to this stock's location (from DB)
          - LOW_STOCK_ALERT_EMAILS from config (optional extra recipients)
        """
        try:
            settings = get_settings()

            result = await self.db.execute(
                select(Stock)
                .options(
                    selectinload(Stock.item),
                    selectinload(Stock.location),
                )
                .where(Stock.id == stock.id)
            )
            loaded_stock = result.scalar_one_or_none()
            if loaded_stock:
                stock = loaded_stock

            min_level = stock.min_level or stock.reorder_point or 0
            if min_level <= 0:
                return

            current_qty = int(stock.quantity_on_hand)
            if current_qty > min_level:
                return

            item_sku = stock.item.sku if stock.item else "Unknown"
            item_name = stock.item.name if stock.item else "Unknown"
            location_name = stock.location.name if stock.location else "Unknown"
            location_id = stock.location_id

            # Find location managers assigned to this location
            from app.models.user import User, UserRole, user_location_association

            loc_mgr_q = (
                select(User)
                .join(user_location_association, User.id == user_location_association.c.user_id)
                .where(
                    user_location_association.c.location_id == location_id,
                    User.is_active == True,  # noqa: E712
                    User.role == UserRole.LOCATION_MANAGER,
                )
            )
            result = await self.db.execute(loc_mgr_q)
            loc_managers = result.scalars().all()

            to_emails = [u.email for u in loc_managers if u.email]

            # Add config-level extra recipients
            if settings.LOW_STOCK_ALERT_EMAILS:
                to_emails.extend(settings.LOW_STOCK_ALERT_EMAILS)

            to_emails = list(set(to_emails))

            if not to_emails:
                logger.debug(f"No recipients for instant low stock alert: {item_sku} at {location_name}")
                return

            from app.services.email_service import get_email_service
            email_service = get_email_service()

            logger.info(
                f"Stock dropped below minimum: {item_sku} at {location_name} "
                f"— Current: {current_qty}, Min: {min_level}"
            )

            success = email_service.send_instant_low_stock_alert(
                to_emails=to_emails,
                item_sku=item_sku,
                item_name=item_name,
                location_name=location_name,
                current_qty=current_qty,
                min_level=min_level,
                action=action,
            )

            if success:
                logger.info(f"Instant low stock alert sent for {item_sku} to {to_emails}")
            else:
                logger.warning(f"Failed to send instant low stock alert for {item_sku}")
                from app.services.notification_service import NotificationService
                body = (
                    f"{item_name} ({item_sku or 'No SKU'}) at {location_name} has "
                    f"quantity {current_qty}; minimum level is {min_level}."
                )
                await NotificationService(self.db).enqueue_email(
                    recipient_emails=to_emails, notification_type="low_stock",
                    subject=f"Low stock: {item_name} at {location_name}",
                    body_html=f"<p>{body}</p>", body_text=body,
                    reference_type="stock", reference_id=stock.id,
                    dedup_key=f"low-stock:{stock.id}:{current_qty}",
                )

        except Exception as e:
            logger.error(f"Error sending low stock alert: {str(e)}")

    async def send_low_stock_alerts(self) -> dict:
        """Send low-stock emails for all stock rows at or below their alert level."""
        from collections import defaultdict
        from app.models.user import User, UserRole, user_location_association
        from app.services.email_service import get_email_service

        settings = get_settings()
        query = (
            select(Stock)
            .options(
                selectinload(Stock.item),
                selectinload(Stock.location),
            )
            .where(
                Stock.reorder_point > 0,
                Stock.quantity_on_hand <= Stock.reorder_point,
            )
        )
        result = await self.db.execute(query)
        low_stock_items = list(result.scalars().unique().all())

        if not low_stock_items:
            return {"count": 0, "recipients": 0, "emails": []}

        location_items: dict = defaultdict(list)
        for stock in low_stock_items:
            location_items[stock.location_id].append({
                "item_sku": stock.item.sku if stock.item else "-",
                "item_name": stock.item.name if stock.item else "Unknown",
                "location_name": stock.location.name if stock.location else "Unknown",
                "location_id": stock.location_id,
                "quantity_on_hand": int(stock.quantity_on_hand),
                "reorder_point": int(stock.reorder_point) if stock.reorder_point else 0,
            })

        email_service = get_email_service()
        total_sent_to: list[str] = []

        for loc_id, items in location_items.items():
            location_name = items[0]["location_name"]
            mgr_q = (
                select(User)
                .join(user_location_association, User.id == user_location_association.c.user_id)
                .where(
                    user_location_association.c.location_id == loc_id,
                    User.is_active == True,
                    User.role == UserRole.LOCATION_MANAGER,
                )
            )
            mgr_result = await self.db.execute(mgr_q)
            mgr_emails = [u.email for u in mgr_result.scalars().all() if u.email]
            if mgr_emails:
                sent = email_service.send_low_stock_alert(mgr_emails, items, location_name=location_name)
                if not sent:
                    from app.services.notification_service import NotificationService
                    body = f"{len(items)} item(s) are at or below reorder level at {location_name}."
                    await NotificationService(self.db).enqueue_email(
                        recipient_emails=mgr_emails, notification_type="low_stock",
                        subject=f"Low-stock alert: {location_name}",
                        body_html=f"<p>{body}</p>", body_text=body,
                        reference_type="location", reference_id=loc_id,
                        dedup_key=f"low-stock-summary:{loc_id}:{date.today().isoformat()}",
                    )
                total_sent_to.extend(mgr_emails)

        hq_q = select(User).where(
            User.is_active == True,
            User.role.in_([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER]),
        )
        hq_result = await self.db.execute(hq_q)
        hq_emails = [u.email for u in hq_result.scalars().all() if u.email]
        if settings.LOW_STOCK_ALERT_EMAILS:
            hq_emails.extend(settings.LOW_STOCK_ALERT_EMAILS)
        hq_emails = list(set(hq_emails))

        if hq_emails:
            all_items = [item for items in location_items.values() for item in items]
            sent = email_service.send_low_stock_alert(hq_emails, all_items)
            if not sent:
                from app.services.notification_service import NotificationService
                body = f"{len(all_items)} item(s) are at or below reorder level company-wide."
                await NotificationService(self.db).enqueue_email(
                    recipient_emails=hq_emails, notification_type="low_stock",
                    subject="Company low-stock summary", body_html=f"<p>{body}</p>",
                    body_text=body, reference_type="low_stock_summary", reference_id="company",
                    dedup_key=f"low-stock-summary:company:{date.today().isoformat()}",
                )
            total_sent_to.extend(hq_emails)

        total_sent_to = sorted(set(total_sent_to))
        return {
            "count": len(low_stock_items),
            "recipients": len(total_sent_to),
            "emails": total_sent_to,
        }
    
    async def get_stock(
        self,
        item_id: str,
        location_id: str,
    ) -> Optional[Stock]:
        """Get stock for an item at a location."""
        result = await self.db.execute(
            select(Stock)
            .options(
                selectinload(Stock.item),
                selectinload(Stock.location),
            )
            .where(
                and_(
                    Stock.item_id == item_id,
                    Stock.location_id == location_id,
                )
            )
        )
        return result.scalar_one_or_none()
    
    async def list_stock(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        location_id: Optional[str] = None,
        item_id: Optional[str] = None,
        category_id: Optional[str] = None,
        asset_type: Optional[str] = None,
        low_stock_only: bool = False,
        out_of_stock_only: bool = False,
        location_ids: Optional[List[str]] = None,
        is_active: Optional[bool] = True,
    ) -> Tuple[List[Stock], int]:
        """
        List stock with filtering.
        
        Returns:
            Tuple of (stock records, total_count)
        """
        query = select(Stock).options(
            selectinload(Stock.item).selectinload(Item.category).selectinload(Category.category_type),
            selectinload(Stock.location),
        )
        if is_active is not None:
            query = query.where(Stock.is_active == is_active)
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(Stock.location_id.in_(location_ids))
        
        joined_item = False

        # Apply filters
        if location_id:
            query = query.where(Stock.location_id == location_id)
        
        if item_id:
            query = query.where(Stock.item_id == item_id)
        
        if category_id:
            query = query.join(Item, Stock.item_id == Item.id)
            joined_item = True
            query = query.where(Item.category_id == category_id)

        if asset_type:
            if not joined_item:
                query = query.join(Item, Stock.item_id == Item.id)
            query = query.where(Item.asset_type == asset_type)
        
        if low_stock_only:
            query = query.where(
                and_(
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_on_hand <= Stock.reorder_point,
                )
            )
        
        if out_of_stock_only:
            query = query.where(Stock.quantity_on_hand <= 0)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(Stock, sort_by):
            order_column = getattr(Stock, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        stocks = list(result.scalars().unique().all())
        
        return stocks, total
    
    async def get_or_create_stock(
        self,
        item_id: str,
        location_id: str,
    ) -> Stock:
        """Get existing stock or create new one."""
        stock = await self.get_stock(item_id, location_id)
        
        if not stock:
            stock = Stock(
                id=self.generate_id(),
                item_id=item_id,
                location_id=location_id,
                quantity_on_hand=0,
                quantity_reserved=0,
                quantity_on_order=0,
            )
            self.db.add(stock)
            await self.db.flush()
        
        return stock

    async def get_stock_for_update(self, item_id: str, location_id: str) -> Optional[Stock]:
        """Lock a stock balance for the duration of a stock-changing transaction."""
        result = await self.db.execute(
            select(Stock).where(
                Stock.item_id == item_id,
                Stock.location_id == location_id,
            ).with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_or_create_stock_for_update(self, item_id: str, location_id: str) -> Stock:
        stock = await self.get_stock_for_update(item_id, location_id)
        if stock:
            return stock
        stock = Stock(
            id=self.generate_id(), item_id=item_id, location_id=location_id,
            quantity_on_hand=0, quantity_reserved=0, quantity_on_order=0,
        )
        self.db.add(stock)
        await self.db.flush()
        return stock
    
    async def adjust_quantity(
        self,
        item_id: str,
        location_id: str,
        adjustment: Decimal,
        reason: Optional[str] = None,
    ) -> Stock:
        """
        Adjust stock quantity.
        
        Args:
            item_id: Item ID
            location_id: Location ID
            adjustment: Positive or negative quantity change
            reason: Reason for adjustment
            
        Returns:
            Updated stock record
        """
        stock = await self.get_or_create_stock_for_update(item_id, location_id)
        
        new_quantity = stock.quantity_on_hand + adjustment
        if new_quantity < 0:
            raise BadRequestError(
                message=f"Cannot reduce stock below 0. Current: {stock.quantity_on_hand}, Adjustment: {adjustment}"
            )
        
        stock.quantity_on_hand = new_quantity
        await self.db.commit()
        await self.db.refresh(stock)
        
        return stock
    
    async def adjust_stock(
        self,
        item_id: str,
        location_id: str,
        quantity_change: int,
        reason: str,
        notes: Optional[str] = None,
        lot_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Adjust stock quantity and create a transaction record.
        
        Args:
            item_id: Item ID
            location_id: Location ID
            quantity_change: Positive or negative quantity change
            reason: Reason for adjustment
            notes: Additional notes
            lot_id: Optional lot ID
            user_id: User making the adjustment
            
        Returns:
            Dict with stock_id, old_quantity, new_quantity
        """
        item = await self._get_item(item_id)
        if item and (item.stock_behavior == "serialized" or item.is_serialized):
            raise BadRequestError(
                message="Equipment and instruments are serialized products. Manage them in Products; stock adjustment is only for quantity-based stock."
            )
        if quantity_change == 0:
            raise BadRequestError(message="Stock adjustment must change the quantity")
        if item and (item.is_lot_tracked or item.has_expiry) and not lot_id:
            raise BadRequestError(
                message="Select the affected lot when adjusting lot-controlled stock"
            )

        # Lock the balance so concurrent adjustments cannot overwrite each other.
        stock = await self.get_or_create_stock_for_update(item_id, location_id)
        old_quantity = int(stock.quantity_on_hand)
        lot = None
        if lot_id:
            lot_result = await self.db.execute(
                select(StockLot)
                .where(
                    StockLot.id == lot_id,
                    StockLot.item_id == item_id,
                    StockLot.location_id == location_id,
                )
                .with_for_update()
            )
            lot = lot_result.scalar_one_or_none()
            if not lot:
                raise BadRequestError(message="Selected lot does not belong to this item and location")
            if lot.quantity_on_hand + quantity_change < 0:
                raise BadRequestError(
                    message=(
                        f"Cannot reduce lot '{lot.lot_number}' below 0. "
                        f"Current: {lot.quantity_on_hand}, Change: {quantity_change}"
                    )
                )
        
        new_quantity = old_quantity + quantity_change
        if new_quantity < 0:
            raise BadRequestError(
                message=f"Cannot reduce stock below 0. Current: {old_quantity}, Change: {quantity_change}"
            )
        
        # Update stock
        stock.quantity_on_hand = new_quantity
        if lot:
            lot.quantity_on_hand += quantity_change
        
        # Create transaction record
        from uuid import uuid4
        from datetime import timezone
        
        transaction = Transaction(
            id=str(uuid4()),
            transaction_type=TransactionType.ADJUSTMENT,
            item_id=item_id,
            location_id=location_id,
            quantity=quantity_change,
            lot_id=lot_id,
            reason=reason,
            notes=notes,
            created_by_id=user_id,
            transaction_date=datetime.now(timezone.utc),
        )
        self.db.add(transaction)
        
        await self.db.commit()
        await self.db.refresh(stock)
        
        # Check and send instant low stock alert if stock was reduced
        if quantity_change < 0:
            await self._check_and_send_low_stock_alert(stock, action="adjustment")
        
        return {
            "stock_id": stock.id,
            "old_quantity": old_quantity,
            "new_quantity": int(stock.quantity_on_hand),
        }
    
    async def issue_stock(
        self,
        item_id: str,
        location_id: str,
        quantity: int,
        reason: str,
        to_location_id: Optional[str] = None,
        reference_number: Optional[str] = None,
        notes: Optional[str] = None,
        lot_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Issue stock (reduce quantity) and create a transaction record.
        
        Args:
            item_id: Item ID
            location_id: Location ID
            quantity: Quantity to issue (must be positive)
            reason: Reason for issuing
            notes: Additional notes
            lot_id: Optional lot ID
            user_id: User making the issue
            
        Returns:
            Dict with stock_id, old_quantity, new_quantity
        """
        if quantity <= 0:
            raise BadRequestError(message="Quantity must be positive")
        item = await self._get_item(item_id)
        if item and (item.stock_behavior == "serialized" or item.is_serialized):
            raise BadRequestError(
                message="Equipment and instruments are serialized products. Use product transfers/status updates; stock issue is only for quantity-based stock."
            )
        
        # Lock the balance before checking and deducting available quantity.
        stock = await self.get_or_create_stock_for_update(item_id, location_id)
        old_quantity = int(stock.quantity_on_hand)
        reserved = int(stock.quantity_reserved)
        available = old_quantity - reserved

        if quantity > available:
            raise BadRequestError(
                message=(
                    f"Insufficient available stock. "
                    f"On hand: {old_quantity}, Reserved: {reserved}, "
                    f"Available: {available}, Requested: {quantity}"
                )
            )
        new_quantity = old_quantity - quantity

        # Create transaction record
        from uuid import uuid4
        from datetime import timezone

        stock.quantity_on_hand = new_quantity
        transaction_date = datetime.now(timezone.utc)
        is_transfer = bool(to_location_id and to_location_id != location_id)

        if is_transfer:
            destination_stock = await self.get_or_create_stock(item_id, to_location_id)
            destination_stock.quantity_on_hand = int(destination_stock.quantity_on_hand) + quantity

            transfer_out = Transaction(
                id=str(uuid4()),
                reference_number=reference_number,
                transaction_type=TransactionType.TRANSFER_OUT,
                item_id=item_id,
                location_id=location_id,
                quantity=quantity,
                reason=reason,
                notes=notes,
                created_by_id=user_id,
                transaction_date=transaction_date,
            )
            transfer_in = Transaction(
                id=str(uuid4()),
                reference_number=reference_number,
                transaction_type=TransactionType.TRANSFER_IN,
                item_id=item_id,
                location_id=to_location_id,
                quantity=quantity,
                reason=reason,
                notes=notes,
                created_by_id=user_id,
                transaction_date=transaction_date,
            )
            self.db.add(transfer_out)
            self.db.add(transfer_in)
        else:
            transaction = Transaction(
                id=str(uuid4()),
                reference_number=reference_number,
                transaction_type=TransactionType.ISSUE,
                item_id=item_id,
                location_id=location_id,
                quantity=quantity,
                reason=reason,
                notes=notes,
                created_by_id=user_id,
                transaction_date=transaction_date,
            )
            self.db.add(transaction)
        
        await self.db.commit()
        await self.db.refresh(stock)
        
        # Check and send instant low stock alert if needed
        await self._check_and_send_low_stock_alert(stock, action="issue")
        
        return {
            "stock_id": stock.id,
            "old_quantity": old_quantity,
            "new_quantity": int(stock.quantity_on_hand),
            "transaction_type": "transfer" if is_transfer else "issue",
        }

    async def _get_item(self, item_id: str):
        """Load item with category type for stock behavior checks."""
        from sqlalchemy.orm import selectinload
        from app.models.item import Item
        from app.models.category import Category

        result = await self.db.execute(
            select(Item)
            .options(selectinload(Item.category).selectinload(Category.category_type))
            .where(Item.id == item_id)
        )
        return result.scalar_one_or_none()
    
    async def reserve_stock(
        self,
        item_id: str,
        location_id: str,
        quantity: Decimal,
        *,
        commit: bool = True,
    ) -> Stock:
        """Reserve stock under a row lock to prevent concurrent overbooking."""
        result = await self.db.execute(
            select(Stock)
            .where(
                Stock.item_id == item_id,
                Stock.location_id == location_id,
                Stock.is_active.is_(True),
            )
            .with_for_update()
        )
        stock = result.scalar_one_or_none()
        
        if not stock:
            raise NotFoundError(
                resource="Stock",
                resource_id=f"{item_id}@{location_id}",
                message="No stock exists for this item at this location",
            )
        
        available = stock.quantity_on_hand - stock.quantity_reserved
        if quantity > available:
            raise BadRequestError(
                message=f"Insufficient available stock. Available: {available}, Requested: {quantity}"
            )
        
        stock.quantity_reserved += int(quantity)
        await self.db.flush()
        if commit:
            await self.db.commit()
            await self.db.refresh(stock)
        
        return stock
    
    async def release_reservation(
        self,
        item_id: str,
        location_id: str,
        quantity: Decimal,
    ) -> Stock:
        """Release previously reserved stock."""
        stock = await self.get_stock(item_id, location_id)
        
        if not stock:
            raise NotFoundError(
                resource="Stock",
                resource_id=f"{item_id}@{location_id}",
            )
        
        stock.quantity_reserved = max(0, stock.quantity_reserved - int(quantity))
        await self.db.commit()
        await self.db.refresh(stock)
        
        return stock
    
    # Stock Lot methods
    
    async def create_lot(
        self,
        item_id: str,
        location_id: str,
        lot_number: str,
        quantity: Decimal,
        expiry_date: Optional[date] = None,
        received_at: Optional[datetime] = None,
        supplier: Optional[str] = None,
        cost_per_unit: Optional[Decimal] = None,
    ) -> StockLot:
        """Create a new stock lot."""
        lot = StockLot(
            id=self.generate_id(),
            item_id=item_id,
            location_id=location_id,
            lot_number=lot_number,
            quantity_on_hand=int(quantity),
            expiry_date=expiry_date,
            received_at=received_at or datetime.utcnow(),
            supplier=supplier,
            cost_per_unit=float(cost_per_unit) if cost_per_unit is not None else None,
        )
        
        self.db.add(lot)
        await self.db.commit()
        await self.db.refresh(lot)
        
        return lot
    
    async def list_lots(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "received_at",
        sort_order: str = "desc",
        filters = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[List[StockLot], int]:
        """List lots with filtering and pagination."""
        query = select(StockLot).options(
            selectinload(StockLot.item),
            selectinload(StockLot.location),
        )

        if location_ids is not None:
            query = query.where(StockLot.location_id.in_(location_ids))

        if filters:
            if getattr(filters, 'item_id', None):
                query = query.where(StockLot.item_id == filters.item_id)
            if getattr(filters, 'location_id', None):
                query = query.where(StockLot.location_id == filters.location_id)
            if getattr(filters, 'lot_number', None):
                query = query.where(StockLot.lot_number.ilike(f"%{filters.lot_number}%"))
            if getattr(filters, 'expired_only', False):
                query = query.where(
                    and_(
                        StockLot.expiry_date.isnot(None),
                        StockLot.expiry_date < date.today(),
                    )
                )
            elif getattr(filters, 'expiring_within_days', None):
                cutoff = date.today() + timedelta(days=filters.expiring_within_days)
                query = query.where(
                    and_(
                        StockLot.expiry_date.isnot(None),
                        StockLot.expiry_date <= cutoff,
                        StockLot.expiry_date >= date.today(),
                    )
                )

        # Count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        # Sorting
        if hasattr(StockLot, sort_by):
            order_column = getattr(StockLot, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        lots = list(result.scalars().unique().all())

        return lots, total

    async def get_lot_by_id(self, lot_id: str) -> Optional[StockLot]:
        """Get a specific stock lot by ID."""
        result = await self.db.execute(
            select(StockLot)
            .options(
                selectinload(StockLot.item),
                selectinload(StockLot.location),
            )
            .where(StockLot.id == lot_id)
        )
        return result.scalar_one_or_none()

    async def update_thresholds(
        self,
        stock_id: str,
        **kwargs,
    ) -> Stock:
        """Update stock threshold levels."""
        result = await self.db.execute(
            select(Stock)
            .options(
                selectinload(Stock.item),
                selectinload(Stock.location),
            )
            .where(Stock.id == stock_id)
        )
        stock = result.scalar_one_or_none()
        if not stock:
            raise NotFoundError(resource="Stock", resource_id=stock_id)

        for key, value in kwargs.items():
            if value is not None and hasattr(stock, key):
                setattr(stock, key, value)

        await self.db.commit()
        await self.db.refresh(stock)
        return await self.get_by_id(stock.id)

    async def correct_location(
        self,
        stock_id: str,
        new_location_id: str,
        user_id: str,
        reason: str,
    ) -> dict:
        """Move or merge a stock balance while preserving historical records."""
        from datetime import timezone
        from uuid import uuid4

        from app.models.location import Location

        stock_result = await self.db.execute(
            select(Stock).where(Stock.id == stock_id).with_for_update()
        )
        stock = stock_result.scalar_one_or_none()
        if not stock:
            raise NotFoundError(resource="Stock", resource_id=stock_id)
        if stock.location_id == new_location_id:
            raise BadRequestError(message="The selected location is already assigned")

        location_result = await self.db.execute(
            select(Location).where(
                Location.id == new_location_id,
                Location.is_active.is_(True),
            )
        )
        if not location_result.scalar_one_or_none():
            raise NotFoundError(resource="Location", resource_id=new_location_id)

        old_location_id = stock.location_id
        quantity = int(stock.quantity_on_hand or 0)
        destination_result = await self.db.execute(
            select(Stock).where(
                Stock.item_id == stock.item_id,
                Stock.location_id == new_location_id,
            ).with_for_update()
        )
        destination = destination_result.scalar_one_or_none()
        merged = destination is not None

        if destination:
            destination.quantity_on_hand += quantity
            destination.quantity_reserved += int(stock.quantity_reserved or 0)
            destination.quantity_on_order += int(stock.quantity_on_order or 0)
            destination.is_active = True
            stock.quantity_on_hand = 0
            stock.quantity_reserved = 0
            stock.quantity_on_order = 0
            stock.is_active = False
        else:
            stock.location_id = new_location_id
            destination = stock

        lots_result = await self.db.execute(
            select(StockLot).where(
                StockLot.item_id == stock.item_id,
                StockLot.location_id == old_location_id,
            )
        )
        for lot in lots_result.scalars().all():
            lot.location_id = new_location_id

        if quantity:
            transaction_date = datetime.now(timezone.utc)
            reference_number = f"LOCATION-CORRECTION-{stock_id[:8]}"
            self.db.add_all([
                Transaction(
                    id=str(uuid4()),
                    transaction_type=TransactionType.TRANSFER_OUT,
                    item_id=stock.item_id,
                    location_id=old_location_id,
                    quantity=quantity,
                    reference_number=reference_number,
                    reason=reason,
                    notes="Stock location correction; historical transactions preserved.",
                    created_by_id=user_id,
                    transaction_date=transaction_date,
                ),
                Transaction(
                    id=str(uuid4()),
                    transaction_type=TransactionType.TRANSFER_IN,
                    item_id=stock.item_id,
                    location_id=new_location_id,
                    quantity=quantity,
                    reference_number=reference_number,
                    reason=reason,
                    notes="Stock location correction; historical transactions preserved.",
                    created_by_id=user_id,
                    transaction_date=transaction_date,
                ),
            ])

        await self.db.commit()
        return {
            "stock_id": destination.id,
            "old_location_id": old_location_id,
            "new_location_id": new_location_id,
            "quantity": quantity,
            "merged": merged,
        }
    
    async def get_expiring_lots(
        self,
        days: int = 30,
        location_ids: Optional[List[str]] = None,
    ) -> List[StockLot]:
        """Get lots expiring within the specified days."""
        cutoff_date = date.today() + timedelta(days=days)
        
        query = (
            select(StockLot)
            .join(Stock)
            .where(
                and_(
                    StockLot.expiry_date.isnot(None),
                    StockLot.expiry_date <= cutoff_date,
                    StockLot.quantity_on_hand > 0,
                )
            )
        )
        
        if location_ids is not None:
            query = query.where(Stock.location_id.in_(location_ids))
        
        query = query.order_by(StockLot.expiry_date.asc())
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def consume_lot(
        self,
        lot_id: str,
        quantity: Decimal,
    ) -> StockLot:
        """Consume quantity from a lot."""
        result = await self.db.execute(
            select(StockLot).where(StockLot.id == lot_id)
        )
        lot = result.scalar_one_or_none()
        
        if not lot:
            raise NotFoundError(resource="Stock Lot", resource_id=lot_id)
        
        if quantity > lot.quantity_on_hand:
            raise BadRequestError(
                message=f"Insufficient lot quantity. Available: {lot.quantity_on_hand}, Requested: {quantity}"
            )
        
        lot.quantity_on_hand -= int(quantity)
        await self.db.commit()
        await self.db.refresh(lot)
        
        return lot
    
    async def get_location_stock_summary(self, location_id: str):
        """
        Get comprehensive stock summary for a location with daily movements.
        
        Returns opening balance, today's movements, and closing balance for each item.
        """
        from datetime import datetime, timezone
        from app.models.location import Location
        from app.models.transaction import Transaction, TransactionType
        from app.schemas.stock import LocationStockSummary, LocationStockItem
        
        # Get location info
        loc_result = await self.db.execute(
            select(Location).where(Location.id == location_id)
        )
        location = loc_result.scalar_one_or_none()
        if not location:
            raise NotFoundError(resource="Location", resource_id=location_id)
        
        # Get all stock for this location with item details
        stock_result = await self.db.execute(
            select(Stock)
            .options(
                selectinload(Stock.item).selectinload(Item.category).selectinload(Category.category_type),
                selectinload(Stock.location),
            )
            .where(Stock.location_id == location_id)
            .where(Stock.is_active.is_(True))
        )
        stocks = list(stock_result.scalars().all())
        
        # Get today's date range
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
        
        # Get today's transactions for this location
        txn_result = await self.db.execute(
            select(Transaction)
            .where(
                and_(
                    Transaction.location_id == location_id,
                    Transaction.transaction_date >= today_start,
                    Transaction.transaction_date <= today_end,
                )
            )
        )
        transactions = list(txn_result.scalars().all())

        latest_activity_result = await self.db.execute(
            select(
                Transaction.item_id,
                func.max(Transaction.transaction_date),
            )
            .where(
                Transaction.location_id == location_id
            )
            .group_by(Transaction.item_id)
        )
        latest_activity_dates = dict(latest_activity_result.all())

        lot_result = await self.db.execute(
            select(StockLot)
            .where(StockLot.location_id == location_id)
            .order_by(StockLot.received_at.desc())
        )
        batches_by_item = {}
        for lot in lot_result.scalars().all():
            batches_by_item.setdefault(lot.item_id, []).append({
                "lot_number": lot.lot_number,
                "quantity_on_hand": lot.quantity_on_hand,
                "quantity_reserved": lot.quantity_reserved,
                "expiry_date": lot.expiry_date,
                "supplier": lot.supplier,
                "received_at": lot.received_at,
            })
        
        # Group transactions by item
        item_movements = {}
        for txn in transactions:
            if txn.item_id not in item_movements:
                item_movements[txn.item_id] = {
                    'received': 0,
                    'issued': 0,
                    'adjusted': 0,
                }
            
            if txn.transaction_type in [TransactionType.RECEIPT, TransactionType.TRANSFER_IN] or (
                txn.transaction_type == TransactionType.RETURN
                and (txn.return_condition or "good") == "good"
            ):
                item_movements[txn.item_id]['received'] += abs(txn.quantity)
            elif txn.transaction_type in [TransactionType.ISSUE, TransactionType.TRANSFER_OUT, TransactionType.SCRAP]:
                item_movements[txn.item_id]['issued'] += abs(txn.quantity)
            elif txn.transaction_type in [TransactionType.ADJUSTMENT, TransactionType.CYCLE_COUNT]:
                item_movements[txn.item_id]['adjusted'] += txn.quantity
        
        # Build stock items list
        items_list = []
        total_quantity = 0
        low_stock_count = 0
        
        for stock in stocks:
            item = stock.item
            movements = item_movements.get(item.id, {'received': 0, 'issued': 0, 'adjusted': 0})
            
            closing_balance = int(stock.quantity_on_hand)
            
            # Calculate opening balance (closing - received + issued - adjusted)
            opening_balance = closing_balance - movements['received'] + movements['issued'] - movements['adjusted']
            
            available = closing_balance - int(stock.quantity_reserved)
            is_low = (
                closing_balance > 0
                and stock.reorder_point
                and closing_balance <= int(stock.reorder_point)
            )
            
            if is_low:
                low_stock_count += 1
            
            total_quantity += closing_balance
            
            items_list.append(LocationStockItem(
                stock_id=stock.id,
                item_id=item.id,
                sku=item.sku,
                name=item.name,
                id_number=item.id_number,
                latest_received_date=latest_activity_dates.get(item.id),
                latest_activity_date=(
                    latest_activity_dates.get(item.id)
                    or stock.created_at
                ),
                description=item.description,
                manufacturer=item.manufacturer,
                model=item.model,
                category_id=item.category_id,
                category_name=item.category.name if item.category else None,
                category_type_name=(
                    item.category.category_type.name
                    if item.category and item.category.category_type
                    else (item.category.name if item.category else None)
                ),
                category_type_key=(
                    item.category.category_type.key
                    if item.category and item.category.category_type
                    else (item.category.category_type_key or item.category.name if item.category else None)
                ),
                stock_behavior=item.stock_behavior,
                is_serialized=item.is_serialized,
                unit_of_measure=item.unit_of_measure,
                opening_balance=max(0, opening_balance),
                received_today=movements['received'],
                issued_today=movements['issued'],
                adjusted_today=movements['adjusted'],
                closing_balance=closing_balance,
                reserved=int(stock.quantity_reserved),
                available=available,
                reorder_point=int(stock.reorder_point) if stock.reorder_point else 0,
                is_low_stock=is_low,
                batches=batches_by_item.get(item.id, []),
            ))
        
        # Sort by name
        items_list.sort(key=lambda x: x.name)
        
        return LocationStockSummary(
            location_id=location.id,
            location_code=location.code,
            location_name=location.name,
            total_items=len(items_list),
            total_quantity=total_quantity,
            low_stock_count=low_stock_count,
            items=items_list,
        )

    async def get_all_locations_stock_summary(self, location_ids: list = None):
        """
        Get stock summary for all locations with daily movements.
        
        Returns aggregate data plus per-location summaries.
        """
        from datetime import datetime, timezone
        from app.models.location import Location
        from app.models.transaction import Transaction, TransactionType
        from app.schemas.stock import AllLocationsStockSummary, LocationStockSummary, LocationStockItem
        
        # Get all active locations (filtered if location_ids provided)
        loc_query = select(Location).where(Location.is_active == True)
        if location_ids is not None:
            loc_query = loc_query.where(Location.id.in_(location_ids))
        
        loc_result = await self.db.execute(loc_query)
        locations = list(loc_result.scalars().all())
        
        # Get today's date range
        today = datetime.now(timezone.utc).date()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
        today_end = datetime.combine(today, datetime.max.time()).replace(tzinfo=timezone.utc)
        
        # Get all transactions for today
        txn_query = select(Transaction).where(
            and_(
                Transaction.transaction_date >= today_start,
                Transaction.transaction_date <= today_end,
            )
        )
        if location_ids is not None:
            txn_query = txn_query.where(Transaction.location_id.in_(location_ids))
        
        txn_result = await self.db.execute(txn_query)
        all_transactions = list(txn_result.scalars().all())

        latest_activity_query = (
            select(
                Transaction.location_id,
                Transaction.item_id,
                func.max(Transaction.transaction_date),
            )
            .group_by(Transaction.location_id, Transaction.item_id)
        )
        if location_ids is not None:
            latest_activity_query = latest_activity_query.where(
                Transaction.location_id.in_(location_ids)
            )
        latest_activity_result = await self.db.execute(latest_activity_query)
        latest_activity_dates = {
            (location_id, item_id): activity_date
            for location_id, item_id, activity_date in latest_activity_result.all()
        }
        
        # Group transactions by location and item
        location_item_movements = {}
        for txn in all_transactions:
            loc_id = txn.location_id
            item_id = txn.item_id
            
            if loc_id not in location_item_movements:
                location_item_movements[loc_id] = {}
            if item_id not in location_item_movements[loc_id]:
                location_item_movements[loc_id][item_id] = {'received': 0, 'issued': 0, 'adjusted': 0}
            
            if txn.transaction_type in [TransactionType.RECEIPT, TransactionType.TRANSFER_IN] or (
                txn.transaction_type == TransactionType.RETURN
                and (txn.return_condition or "good") == "good"
            ):
                location_item_movements[loc_id][item_id]['received'] += txn.quantity
            elif txn.transaction_type in [TransactionType.ISSUE, TransactionType.TRANSFER_OUT, TransactionType.SCRAP]:
                location_item_movements[loc_id][item_id]['issued'] += txn.quantity
            elif txn.transaction_type in [TransactionType.ADJUSTMENT, TransactionType.CYCLE_COUNT]:
                location_item_movements[loc_id][item_id]['adjusted'] += txn.quantity
        
        # Get all stock records
        stock_query = select(Stock).options(
            selectinload(Stock.item).selectinload(Item.category).selectinload(Category.category_type),
            selectinload(Stock.location),
        )
        stock_query = stock_query.where(Stock.is_active.is_(True))
        if location_ids is not None:
            stock_query = stock_query.where(Stock.location_id.in_(location_ids))
        
        stock_result = await self.db.execute(stock_query)
        all_stocks = list(stock_result.scalars().all())

        lot_query = select(StockLot).order_by(StockLot.received_at.desc())
        if location_ids is not None:
            lot_query = lot_query.where(StockLot.location_id.in_(location_ids))
        lot_result = await self.db.execute(lot_query)
        batches_by_location_item = {}
        for lot in lot_result.scalars().all():
            batches_by_location_item.setdefault((lot.location_id, lot.item_id), []).append({
                "lot_number": lot.lot_number,
                "quantity_on_hand": lot.quantity_on_hand,
                "quantity_reserved": lot.quantity_reserved,
                "expiry_date": lot.expiry_date,
                "supplier": lot.supplier,
                "received_at": lot.received_at,
            })
        
        # Group stocks by location
        location_stocks = {}
        for stock in all_stocks:
            loc_id = stock.location_id
            if loc_id not in location_stocks:
                location_stocks[loc_id] = []
            location_stocks[loc_id].append(stock)
        
        # Build location summaries
        location_summaries = []
        grand_total_items = 0
        grand_total_quantity = 0
        grand_total_received = 0
        grand_total_issued = 0
        grand_total_adjusted = 0
        grand_low_stock_count = 0
        
        for location in locations:
            stocks = location_stocks.get(location.id, [])
            movements = location_item_movements.get(location.id, {})
            
            items_list = []
            total_quantity = 0
            low_stock_count = 0
            loc_received = 0
            loc_issued = 0
            loc_adjusted = 0
            
            for stock in stocks:
                item = stock.item
                item_mov = movements.get(item.id, {'received': 0, 'issued': 0, 'adjusted': 0})
                
                closing_balance = int(stock.quantity_on_hand)
                # Formula: Opening + Received - Issued ± Adjusted = Closing
                # So: Opening = Closing - Received + Issued - Adjusted
                opening_balance = closing_balance - item_mov['received'] + item_mov['issued'] - item_mov['adjusted']
                available = closing_balance - int(stock.quantity_reserved)
                is_low = (
                    closing_balance > 0
                    and stock.reorder_point
                    and closing_balance <= int(stock.reorder_point)
                )
                
                if is_low:
                    low_stock_count += 1
                
                total_quantity += closing_balance
                # Track absolute values for totals (received adds, issued subtracts)
                loc_received += item_mov['received']
                loc_issued += item_mov['issued']
                loc_adjusted += item_mov['adjusted']
                
                items_list.append(LocationStockItem(
                    stock_id=stock.id,
                    item_id=item.id,
                    sku=item.sku,
                    name=item.name,
                    id_number=item.id_number,
                    latest_received_date=latest_activity_dates.get((location.id, item.id)),
                    latest_activity_date=(
                        latest_activity_dates.get((location.id, item.id))
                        or stock.created_at
                    ),
                    description=item.description,
                    manufacturer=item.manufacturer,
                    model=item.model,
                    category_id=item.category_id,
                    category_name=item.category.name if item.category else None,
                    category_type_name=(
                        item.category.category_type.name
                        if item.category and item.category.category_type
                        else (item.category.name if item.category else None)
                    ),
                    category_type_key=(
                        item.category.category_type.key
                        if item.category and item.category.category_type
                        else (item.category.category_type_key or item.category.name if item.category else None)
                    ),
                    stock_behavior=item.stock_behavior,
                    is_serialized=item.is_serialized,
                    unit_of_measure=item.unit_of_measure,
                    opening_balance=max(0, opening_balance),
                    received_today=item_mov['received'],
                    issued_today=item_mov['issued'],
                    adjusted_today=item_mov['adjusted'],
                    closing_balance=closing_balance,
                    reserved=int(stock.quantity_reserved),
                    available=available,
                    reorder_point=int(stock.reorder_point) if stock.reorder_point else 0,
                    is_low_stock=is_low,
                    batches=batches_by_location_item.get((location.id, item.id), []),
                ))
            
            items_list.sort(key=lambda x: x.name)
            
            location_summaries.append(LocationStockSummary(
                location_id=location.id,
                location_code=location.code,
                location_name=location.name,
                total_items=len(items_list),
                total_quantity=total_quantity,
                low_stock_count=low_stock_count,
                items=items_list,
            ))
            
            grand_total_items += len(items_list)
            grand_total_quantity += total_quantity
            grand_total_received += loc_received
            grand_total_issued += loc_issued
            grand_total_adjusted += loc_adjusted
            grand_low_stock_count += low_stock_count
        
        # Sort locations by name
        location_summaries.sort(key=lambda x: x.location_name)
        
        return AllLocationsStockSummary(
            total_items=grand_total_items,
            total_quantity=grand_total_quantity,
            total_received_today=grand_total_received,
            total_issued_today=grand_total_issued,
            total_adjusted_today=grand_total_adjusted,
            low_stock_count=grand_low_stock_count,
            locations=location_summaries,
        )

