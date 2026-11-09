"""
Item Service

Handles inventory item management operations.
"""

from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.item import Item, ItemAttribute
from app.models.category import Category
from app.models.stock import Stock, StockLot
from app.models.asset import SerializedAsset
from app.models.purchase_indent import PurchaseIndentItem
from app.models.transaction import Transaction
from app.models.transfer import TransferItem
from app.services.base_service import BaseService


class ItemService(BaseService[Item]):
    """Service for item management."""
    
    @property
    def model(self):
        return Item
    
    async def get_by_id(self, id: str) -> Optional[Item]:
        """Get item with attributes."""
        result = await self.db.execute(
            select(Item)
            .options(
                selectinload(Item.category).selectinload(Category.category_type),
                selectinload(Item.attributes),
            )
            .where(Item.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_sku(self, sku: Optional[str]) -> Optional[Item]:
        """Get item by SKU."""
        if not sku or not sku.strip():
            return None
        result = await self.db.execute(
            select(Item)
            .options(
                selectinload(Item.category).selectinload(Category.category_type),
                selectinload(Item.attributes),
            )
            .where(Item.sku == sku.upper())
        )
        return result.scalar_one_or_none()

    async def find_probable_duplicates(
        self,
        name: str,
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        exclude_item_id: Optional[str] = None,
    ) -> List[Item]:
        """Find active items with the same normalized identifying fields."""
        query = select(Item).where(
            Item.is_active.is_(True),
            func.lower(func.trim(Item.name)) == name.strip().lower(),
        )
        if manufacturer and manufacturer.strip():
            query = query.where(
                func.lower(func.trim(Item.manufacturer)) == manufacturer.strip().lower()
            )
        if model and model.strip():
            query = query.where(func.lower(func.trim(Item.model)) == model.strip().lower())
        if exclude_item_id:
            query = query.where(Item.id != exclude_item_id)
        result = await self.db.execute(
            query.options(
                selectinload(Item.category).selectinload(Category.category_type),
                selectinload(Item.attributes),
            ).order_by(Item.name.asc()).limit(10)
        )
        return list(result.scalars().unique().all())

    async def get_active_items(self, category_id: Optional[str] = None) -> List[Item]:
        """Get active items for dropdowns and selectors."""
        query = (
            select(Item)
            .options(
                selectinload(Item.category).selectinload(Category.category_type),
                selectinload(Item.attributes),
            )
            .where(Item.is_active.is_(True))
            .order_by(Item.name.asc())
        )

        if category_id:
            query = query.where(Item.category_id == category_id)

        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def list_items(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
        category_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        is_serialized: Optional[bool] = None,
        track_expiry: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[Item], int]:
        """
        List items with filtering.
        
        Returns:
            Tuple of (items, total_count)
        """
        query = select(Item).options(
            selectinload(Item.category).selectinload(Category.category_type),
            selectinload(Item.attributes),
        )
        
        # Apply filters
        if category_id:
            query = query.where(Item.category_id == category_id)
        
        if is_active is not None:
            query = query.where(Item.is_active == is_active)
        
        if is_serialized is not None:
            query = query.where(Item.is_serialized == is_serialized)
        
        if track_expiry is not None:
            query = query.where(Item.has_expiry == track_expiry)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    Item.name.ilike(search_pattern),
                    Item.sku.ilike(search_pattern),
                    Item.description.ilike(search_pattern),
                    Item.manufacturer.ilike(search_pattern),
                )
            )
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(Item, sort_by):
            order_column = getattr(Item, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        items = list(result.scalars().unique().all())
        
        return items, total
    
    async def create_item(
        self,
        sku: Optional[str],
        name: str,
        category_id: str,
        description: Optional[str] = None,
        unit_of_measure: str = "EA",
        manufacturer: Optional[str] = None,
        model: Optional[str] = None,
        standard_cost: Optional[float] = None,
        is_serialized: bool = False,
        is_lot_tracked: bool = False,
        requires_calibration: bool = False,
        calibration_interval_days: Optional[int] = None,
        has_expiry: bool = False,
        shelf_life_days: Optional[int] = None,
        hazardous: bool = False,
        hazard_class: Optional[str] = None,
        is_active: bool = True,
        attributes: Optional[List[Dict[str, Any]]] = None,
    ) -> Item:
        """
        Create a new item.
        
        Returns:
            Created item
            
        Raises:
            BadRequestError: If SKU already exists
            NotFoundError: If category not found
        """
        # Check SKU uniqueness
        normalized_sku = sku.strip().upper() if sku and sku.strip() else None
        existing = await self.get_by_sku(normalized_sku)
        if normalized_sku and existing:
            raise BadRequestError(message=f"SKU '{sku}' already exists")
        
        # Validate category
        if category_id:
            result = await self.db.execute(
                select(Category).where(Category.id == category_id)
            )
            if not result.scalar_one_or_none():
                raise NotFoundError(resource="Category", resource_id=category_id)
        
        # Create item
        item = Item(
            id=self.generate_id(),
            sku=normalized_sku,
            name=name,
            category_id=category_id,
            description=description,
            unit_of_measure=unit_of_measure,
            manufacturer=manufacturer,
            model=model,
            standard_cost=standard_cost,
            is_serialized=is_serialized,
            is_lot_tracked=is_lot_tracked,
            requires_calibration=requires_calibration,
            calibration_interval_days=calibration_interval_days,
            has_expiry=has_expiry,
            shelf_life_days=shelf_life_days,
            hazardous=hazardous,
            hazard_class=hazard_class,
            is_active=is_active,
        )
        
        self.db.add(item)
        await self.db.flush()
        
        # Add attributes
        if attributes:
            for attr_data in attributes:
                attr = ItemAttribute(
                    id=self.generate_id(),
                    item_id=item.id,
                    attribute_name=attr_data.get("attribute_name"),
                    attribute_value=attr_data.get("attribute_value"),
                )
                self.db.add(attr)
        
        await self.db.commit()
        
        # Reload with relationships to avoid lazy loading issues
        return await self.get_by_id(item.id)
    
    async def update_item(
        self,
        item_id: str,
        **kwargs,
    ) -> Item:
        """
        Update an item.
        
        Returns:
            Updated item
            
        Raises:
            NotFoundError: If item not found
            BadRequestError: If SKU conflict
        """
        item = await self.get_by_id(item_id)
        if not item:
            raise NotFoundError(resource="Item", resource_id=item_id)
        
        # Check SKU uniqueness
        if "sku" in kwargs:
            raw_sku = kwargs.pop("sku")
            sku = raw_sku.strip().upper() if raw_sku and raw_sku.strip() else None
            if sku != item.sku:
                existing = await self.get_by_sku(sku)
                if sku and existing:
                    raise BadRequestError(message=f"SKU '{sku}' already exists")
                item.sku = sku
        
        # Update remaining fields
        for key, value in kwargs.items():
            if value is not None and hasattr(item, key) and key != "attributes":
                setattr(item, key, value)
        
        await self.db.commit()
        
        # Reload with relationships to avoid lazy loading issues
        return await self.get_by_id(item_id)
    
    async def add_attribute(
        self,
        item_id: str,
        attribute_name: str,
        attribute_value: str,
    ) -> ItemAttribute:
        """Add an attribute to an item."""
        item = await self.get_by_id(item_id)
        if not item:
            raise NotFoundError(resource="Item", resource_id=item_id)
        
        attr = ItemAttribute(
            id=self.generate_id(),
            item_id=item_id,
            attribute_name=attribute_name,
            attribute_value=attribute_value,
        )
        
        self.db.add(attr)
        await self.db.commit()
        await self.db.refresh(attr)
        
        return attr
    
    async def update_attribute(
        self,
        attribute_id: str,
        attribute_name: Optional[str] = None,
        attribute_value: Optional[str] = None,
    ) -> ItemAttribute:
        """Update an item attribute."""
        result = await self.db.execute(
            select(ItemAttribute).where(ItemAttribute.id == attribute_id)
        )
        attr = result.scalar_one_or_none()
        
        if not attr:
            raise NotFoundError(resource="Item Attribute", resource_id=attribute_id)
        
        if attribute_name is not None:
            attr.attribute_name = attribute_name
        if attribute_value is not None:
            attr.attribute_value = attribute_value
        
        await self.db.commit()
        await self.db.refresh(attr)
        
        return attr
    
    async def delete_attribute(self, attribute_id: str) -> bool:
        """Delete an item attribute."""
        result = await self.db.execute(
            select(ItemAttribute).where(ItemAttribute.id == attribute_id)
        )
        attr = result.scalar_one_or_none()
        
        if not attr:
            raise NotFoundError(resource="Item Attribute", resource_id=attribute_id)
        
        await self.db.delete(attr)
        await self.db.commit()
        
        return True

    async def remove_attribute(self, item_id: str, attribute_id: str) -> bool:
        """Delete an attribute only if it belongs to the given item."""
        result = await self.db.execute(
            select(ItemAttribute).where(
                ItemAttribute.id == attribute_id,
                ItemAttribute.item_id == item_id,
            )
        )
        attr = result.scalar_one_or_none()

        if not attr:
            return False

        await self.db.delete(attr)
        await self.db.commit()

        return True

    async def has_stock(self, item_id: str) -> bool:
        """Check whether an item has any stock quantity or reservation."""
        stock_result = await self.db.execute(
            select(func.count(Stock.id)).where(
                Stock.item_id == item_id,
                or_(
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_reserved > 0,
                    Stock.quantity_on_order > 0,
                ),
            )
        )
        if stock_result.scalar_one() > 0:
            return True

        lot_result = await self.db.execute(
            select(func.count(StockLot.id)).where(
                StockLot.item_id == item_id,
                or_(
                    StockLot.quantity_on_hand > 0,
                    StockLot.quantity_reserved > 0,
                ),
            )
        )
        return lot_result.scalar_one() > 0

    async def get_delete_blockers(self, item_id: str) -> Dict[str, int]:
        """Return related records that make hard deletion unsafe."""
        checks = {
            "stock records": Stock,
            "stock lots": StockLot,
            "serialized assets": SerializedAsset,
            "transactions": Transaction,
            "transfer lines": TransferItem,
            "purchase indent lines": PurchaseIndentItem,
        }
        blockers: Dict[str, int] = {}

        for label, model in checks.items():
            result = await self.db.execute(
                select(func.count(model.id)).where(model.item_id == item_id)
            )
            count = result.scalar_one()
            if count:
                blockers[label] = count

        return blockers

    async def has_business_history(self, item_id: str) -> bool:
        """Whether inventory or historical records already depend on the item definition."""
        return bool(await self.get_delete_blockers(item_id))

    async def get_deactivation_blockers(self, item_id: str) -> Dict[str, int]:
        """Return current inventory that must be cleared before item deactivation."""
        blockers: Dict[str, int] = {}
        stock_count = (await self.db.execute(
            select(func.count(Stock.id)).where(
                Stock.item_id == item_id,
                or_(
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_reserved > 0,
                    Stock.quantity_on_order > 0,
                ),
            )
        )).scalar_one()
        if stock_count:
            blockers["current stock"] = stock_count
        asset_count = (await self.db.execute(
            select(func.count(SerializedAsset.id)).where(SerializedAsset.item_id == item_id)
        )).scalar_one()
        if asset_count:
            blockers["serialized assets"] = asset_count
        return blockers
    
    async def delete_item(self, item_id: str) -> bool:
        """Hard delete an unused item."""
        item = await self.get_by_id(item_id)
        if not item:
            raise NotFoundError(resource="Item", resource_id=item_id)
        
        await self.db.delete(item)
        await self.db.commit()
        
        return True
