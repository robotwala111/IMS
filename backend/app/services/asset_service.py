"""
Asset Service

Handles serialized asset management.
"""

from datetime import datetime, date
from typing import Optional, List, Tuple

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.asset import SerializedAsset, AssetStatus
from app.models.item import Item
from app.models.location import Location
from app.models.transfer import Transfer, TransferItem, TransferStatus
from app.services.base_service import BaseService


class AssetService(BaseService[SerializedAsset]):
    """Service for serialized asset management."""

    ALLOWED_STATUS_TRANSITIONS = {
        AssetStatus.IN_SERVICE: {
            AssetStatus.UNDER_MAINTENANCE, AssetStatus.UNDER_CALIBRATION,
            AssetStatus.OUT_OF_SERVICE, AssetStatus.LOST, AssetStatus.RETIRED,
            AssetStatus.TRANSFERRED,
        },
        AssetStatus.UNDER_MAINTENANCE: {
            AssetStatus.IN_SERVICE, AssetStatus.OUT_OF_SERVICE, AssetStatus.RETIRED,
        },
        AssetStatus.UNDER_CALIBRATION: {
            AssetStatus.IN_SERVICE, AssetStatus.OUT_OF_SERVICE, AssetStatus.RETIRED,
        },
        AssetStatus.OUT_OF_SERVICE: {
            AssetStatus.IN_SERVICE, AssetStatus.UNDER_MAINTENANCE,
            AssetStatus.UNDER_CALIBRATION, AssetStatus.RETIRED,
        },
        AssetStatus.LOST: {AssetStatus.IN_SERVICE, AssetStatus.RETIRED},
        AssetStatus.TRANSFERRED: {AssetStatus.IN_SERVICE, AssetStatus.OUT_OF_SERVICE},
        AssetStatus.RETIRED: set(),
    }
    
    @property
    def model(self):
        return SerializedAsset
    
    async def get_by_id(self, id: str) -> Optional[SerializedAsset]:
        """Get asset with related data."""
        result = await self.db.execute(
            select(SerializedAsset)
            .options(
                selectinload(SerializedAsset.item),
                selectinload(SerializedAsset.location),
                selectinload(SerializedAsset.assigned_to),
                selectinload(SerializedAsset.calibration_records),
                selectinload(SerializedAsset.maintenance_records),
            )
            .where(SerializedAsset.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_serial_number(self, serial_number: str) -> Optional[SerializedAsset]:
        """Get asset by serial number."""
        result = await self.db.execute(
            select(SerializedAsset)
            .options(
                selectinload(SerializedAsset.item),
                selectinload(SerializedAsset.location),
                selectinload(SerializedAsset.assigned_to),
                selectinload(SerializedAsset.calibration_records),
                selectinload(SerializedAsset.maintenance_records),
            )
            .where(SerializedAsset.serial_number == serial_number)
        )
        return result.scalar_one_or_none()
    
    async def list_assets(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "serial_number",
        sort_order: str = "asc",
        location_id: Optional[str] = None,
        item_id: Optional[str] = None,
        status: Optional[str] = None,
        assigned_to_id: Optional[str] = None,
        search: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
        filters=None,  # accepts AssetSearchParams object from endpoint
    ) -> Tuple[List[SerializedAsset], int]:
        """
        List assets with filtering.
        
        Returns:
            Tuple of (assets, total_count)
        """
        # Unpack filters object if provided (from endpoint)
        if filters is not None:
            location_id = filters.location_id or location_id
            item_id = filters.item_id or item_id
            status = filters.status or status
            assigned_to_id = filters.assigned_to_user_id or assigned_to_id
            search = filters.search or search

        query = select(SerializedAsset).options(
            selectinload(SerializedAsset.item),
            selectinload(SerializedAsset.location),
            selectinload(SerializedAsset.assigned_to),
            selectinload(SerializedAsset.calibration_records),
        )
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        # Apply filters
        if location_id:
            query = query.where(SerializedAsset.location_id == location_id)
        
        if item_id:
            query = query.where(SerializedAsset.item_id == item_id)
        
        if status:
            query = query.where(SerializedAsset.status == status)
        
        if assigned_to_id:
            query = query.where(SerializedAsset.assigned_to_user_id == assigned_to_id)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    SerializedAsset.serial_number.ilike(search_pattern),
                    SerializedAsset.asset_tag.ilike(search_pattern),
                    SerializedAsset.notes.ilike(search_pattern),
                )
            )
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(SerializedAsset, sort_by):
            order_column = getattr(SerializedAsset, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc(), SerializedAsset.id.desc())
            else:
                query = query.order_by(order_column.asc(), SerializedAsset.id.asc())
        else:
            query = query.order_by(
                SerializedAsset.created_at.desc(),
                SerializedAsset.id.desc(),
            )
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        assets = list(result.scalars().unique().all())
        
        return assets, total
    
    async def create_asset(
        self,
        serial_number: str,
        item_id: str,
        location_id: str,
        status: str = "in_service",
        asset_tag: Optional[str] = None,
        acquired_at: Optional[date] = None,
        supplier_name: Optional[str] = None,
        invoice_number: Optional[str] = None,
        purchase_order: Optional[str] = None,
        cost: Optional[float] = None,
        warranty_expiry: Optional[date] = None,
        assigned_to_user_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> SerializedAsset:
        """
        Create a new serialized asset.
        
        Returns:
            Created asset
            
        Raises:
            BadRequestError: If serial number already exists
            NotFoundError: If item or location not found
        """
        # Check serial number uniqueness
        existing = await self.get_by_serial_number(serial_number)
        if existing:
            raise BadRequestError(message=f"Serial number '{serial_number}' already exists")
        
        # Validate item
        result = await self.db.execute(select(Item).where(Item.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            raise NotFoundError(resource="Item", resource_id=item_id)
        
        if not item.is_serialized:
            raise BadRequestError(message=f"Item {item.sku} is not configured as serialized")
        
        # Validate location
        result = await self.db.execute(select(Location).where(Location.id == location_id))
        if not result.scalar_one_or_none():
            raise NotFoundError(resource="Location", resource_id=location_id)
        
        # Create asset
        asset = SerializedAsset(
            id=self.generate_id(),
            serial_number=serial_number,
            item_id=item_id,
            location_id=location_id,
            status=status,
            asset_tag=asset_tag,
            acquired_at=acquired_at,
            supplier_name=supplier_name,
            invoice_number=invoice_number,
            purchase_order=purchase_order,
            cost=cost,
            warranty_expiry=warranty_expiry,
            assigned_to_user_id=assigned_to_user_id,
            notes=notes,
        )
        
        self.db.add(asset)
        await self.db.commit()
        await self.db.refresh(asset)
        
        return asset
    
    async def update_asset(
        self,
        asset_id: str,
        **kwargs,
    ) -> SerializedAsset:
        """
        Update an asset.
        
        Returns:
            Updated asset
            
        Raises:
            NotFoundError: If asset not found
            BadRequestError: If serial number conflict
        """
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise NotFoundError(resource="Asset", resource_id=asset_id)

        next_status = kwargs.get("status")
        if next_status is not None:
            self.validate_status_transition(asset.status, next_status)
        next_location = kwargs.get("location_id")
        if next_location and next_location != asset.location_id:
            if await self.has_active_transfer(asset):
                raise BadRequestError(
                    message="Cannot directly change location while this asset is in an active transfer. Complete or cancel the transfer first."
                )
        
        # Check serial number uniqueness
        if "serial_number" in kwargs and kwargs["serial_number"]:
            serial = kwargs["serial_number"]
            if serial != asset.serial_number:
                existing = await self.get_by_serial_number(serial)
                if existing:
                    raise BadRequestError(message=f"Serial number '{serial}' already exists")
                asset.serial_number = serial
            del kwargs["serial_number"]
        
        # Update fields
        for key, value in kwargs.items():
            if value is not None and hasattr(asset, key):
                setattr(asset, key, value)
        
        await self.db.commit()
        await self.db.refresh(asset)
        
        return asset

    @classmethod
    def validate_status_transition(cls, current, target) -> None:
        current_status = current if isinstance(current, AssetStatus) else AssetStatus(current)
        target_status = target if isinstance(target, AssetStatus) else AssetStatus(target)
        if target_status == current_status:
            return
        if target_status not in cls.ALLOWED_STATUS_TRANSITIONS[current_status]:
            raise BadRequestError(
                message=f"Asset status cannot change from {current_status.value} to {target_status.value}."
            )

    async def has_active_transfer(self, asset: SerializedAsset) -> bool:
        """Check whether the asset serial is already part of an unfinished transfer."""
        pattern = f'%"{asset.serial_number}"%'
        result = await self.db.execute(
            select(Transfer.id)
            .join(TransferItem, TransferItem.transfer_id == Transfer.id)
            .where(
                Transfer.status.in_((
                    TransferStatus.REQUESTED, TransferStatus.APPROVED,
                    TransferStatus.IN_TRANSIT, TransferStatus.PARTIALLY_RECEIVED,
                )),
                TransferItem.serial_numbers.like(pattern),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
    
    async def transfer_asset(
        self,
        asset_id: str,
        new_location_id: str,
        transferred_by_id: str,
    ) -> SerializedAsset:
        """Transfer an asset to a new location."""
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise NotFoundError(resource="Asset", resource_id=asset_id)
        
        # Validate location
        result = await self.db.execute(
            select(Location).where(Location.id == new_location_id)
        )
        if not result.scalar_one_or_none():
            raise NotFoundError(resource="Location", resource_id=new_location_id)
        
        asset.location_id = new_location_id
        await self.db.commit()
        await self.db.refresh(asset)
        
        return asset
    
    async def assign_asset(
        self,
        asset_id: str,
        assigned_to_id: Optional[str],
    ) -> SerializedAsset:
        """Assign or unassign an asset to a user."""
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise NotFoundError(resource="Asset", resource_id=asset_id)
        
        asset.assigned_to_user_id = assigned_to_id
        await self.db.commit()
        await self.db.refresh(asset)
        
        return asset
    
    async def update_status(
        self,
        asset_id: str,
        status: str,
    ) -> SerializedAsset:
        """Update asset status."""
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise NotFoundError(resource="Asset", resource_id=asset_id)
        
        valid_statuses = [s.value for s in AssetStatus]
        if status not in valid_statuses:
            raise BadRequestError(
                message=f"Invalid status '{status}'",
                details={"valid_statuses": valid_statuses},
            )
        
        self.validate_status_transition(asset.status, status)
        asset.status = status
        await self.db.commit()
        await self.db.refresh(asset)
        
        return asset
    
    async def delete_asset(self, asset_id: str) -> bool:
        """Soft delete an asset by retiring it."""
        asset = await self.get_by_id(asset_id)
        if not asset:
            raise NotFoundError(resource="Asset", resource_id=asset_id)
        
        self.validate_status_transition(asset.status, AssetStatus.RETIRED)
        asset.status = AssetStatus.RETIRED
        await self.db.commit()
        
        return True
