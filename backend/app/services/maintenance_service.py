"""
Maintenance Service

Handles maintenance record management for serialized assets.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.maintenance import MaintenanceRecord
from app.models.asset import AssetStatus, SerializedAsset
from app.services.base_service import BaseService


class MaintenanceService(BaseService[MaintenanceRecord]):
    """Service for maintenance record management."""
    
    @property
    def model(self):
        return MaintenanceRecord

    @staticmethod
    def _validate_dates(
        scheduled_at: datetime,
        completed_at: Optional[datetime] = None,
        next_maintenance_due: Optional[datetime] = None,
    ) -> None:
        if completed_at is not None and completed_at < scheduled_at:
            raise BadRequestError(
                message="Maintenance completion cannot be before its scheduled date"
            )
        if next_maintenance_due is not None:
            reference = completed_at or scheduled_at
            if next_maintenance_due <= reference:
                raise BadRequestError(
                    message="Next maintenance due must be after the current maintenance date"
                )

    async def _lock_and_validate_asset(
        self, asset_id: str, *, exclude_record_id: Optional[str] = None,
        maintenance_start: Optional[datetime] = None,
        maintenance_end: Optional[datetime] = None,
    ) -> SerializedAsset:
        asset_result = await self.db.execute(
            select(SerializedAsset)
            .where(SerializedAsset.id == asset_id)
            .with_for_update()
        )
        asset = asset_result.scalar_one_or_none()
        if not asset:
            raise NotFoundError(resource="Asset", resource_id=asset_id)
        if asset.status in {AssetStatus.RETIRED, AssetStatus.LOST}:
            raise BadRequestError(
                message=f"Maintenance cannot be recorded for a {asset.status.value} asset"
            )
        if maintenance_start is not None:
            overlap_query = select(MaintenanceRecord.id).where(
                MaintenanceRecord.asset_id == asset_id,
                or_(
                    MaintenanceRecord.completed_at.is_(None),
                    MaintenanceRecord.completed_at >= maintenance_start,
                ),
            )
            if maintenance_end is not None:
                overlap_query = overlap_query.where(
                    MaintenanceRecord.scheduled_at <= maintenance_end
                )
            if exclude_record_id:
                overlap_query = overlap_query.where(MaintenanceRecord.id != exclude_record_id)
            overlap_result = await self.db.execute(overlap_query.limit(1))
            if overlap_result.scalar_one_or_none() is not None:
                raise BadRequestError(
                    message="Asset already has an overlapping maintenance record"
                )
        return asset
    
    async def get_by_id(self, id: str) -> Optional[MaintenanceRecord]:
        """Get maintenance record with related data."""
        result = await self.db.execute(
            select(MaintenanceRecord)
            .options(
                selectinload(MaintenanceRecord.asset).selectinload(SerializedAsset.location),
                selectinload(MaintenanceRecord.assigned_to),
                selectinload(MaintenanceRecord.completed_by),
            )
            .where(MaintenanceRecord.id == id)
        )
        return result.scalar_one_or_none()
    
    async def list_records(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "scheduled_at",
        sort_order: str = "desc",
        asset_id: Optional[str] = None,
        location_id: Optional[str] = None,
        maintenance_type: Optional[str] = None,
        due_before: Optional[date] = None,
        completed: Optional[bool] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[List[MaintenanceRecord], int]:
        """
        List maintenance records with filtering.
        
        Returns:
            Tuple of (records, total_count)
        """
        query = select(MaintenanceRecord).options(
            selectinload(MaintenanceRecord.asset).selectinload(SerializedAsset.location),
            selectinload(MaintenanceRecord.assigned_to),
        )
        
        # Join with asset for location filtering
        query = query.join(SerializedAsset)
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        # Apply filters
        if asset_id:
            query = query.where(MaintenanceRecord.asset_id == asset_id)
        
        if location_id:
            query = query.where(SerializedAsset.location_id == location_id)
        
        if maintenance_type:
            query = query.where(MaintenanceRecord.maintenance_type == maintenance_type)
        
        if due_before:
            query = query.where(MaintenanceRecord.scheduled_at <= due_before)
        
        if completed is not None:
            if completed:
                query = query.where(MaintenanceRecord.completed_at.isnot(None))
            else:
                query = query.where(MaintenanceRecord.completed_at.is_(None))
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(MaintenanceRecord, sort_by):
            order_column = getattr(MaintenanceRecord, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        records = list(result.scalars().unique().all())
        
        return records, total
    
    async def get_due_soon(
        self,
        days: int = 30,
        location_ids: Optional[List[str]] = None,
    ) -> List[MaintenanceRecord]:
        """Get maintenance scheduled within specified days."""
        today = datetime.utcnow()
        due_date = today + timedelta(days=days)
        
        query = (
            select(MaintenanceRecord)
            .options(
                selectinload(MaintenanceRecord.asset).selectinload(SerializedAsset.location),
            )
            .join(SerializedAsset)
            .where(
                and_(
                    MaintenanceRecord.scheduled_at >= today,
                    MaintenanceRecord.scheduled_at <= due_date,
                    MaintenanceRecord.completed_at.is_(None),
                )
            )
        )
        
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        query = query.order_by(MaintenanceRecord.scheduled_at.asc())
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def get_overdue(
        self,
        location_ids: Optional[List[str]] = None,
    ) -> List[MaintenanceRecord]:
        """Get overdue maintenance records."""
        today = datetime.utcnow()
        
        query = (
            select(MaintenanceRecord)
            .options(
                selectinload(MaintenanceRecord.asset).selectinload(SerializedAsset.location),
            )
            .join(SerializedAsset)
            .where(
                and_(
                    MaintenanceRecord.scheduled_at < today,
                    MaintenanceRecord.completed_at.is_(None),
                )
            )
        )
        
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        query = query.order_by(MaintenanceRecord.scheduled_at.asc())
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def get_asset_history(self, asset_id: str) -> List[MaintenanceRecord]:
        """Get maintenance history for an asset."""
        query = (
            select(MaintenanceRecord)
            .options(
                selectinload(MaintenanceRecord.assigned_to),
                selectinload(MaintenanceRecord.completed_by),
            )
            .where(MaintenanceRecord.asset_id == asset_id)
            .order_by(MaintenanceRecord.scheduled_at.desc())
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def create(
        self,
        asset_id: str,
        performed_by_id: str,
        maintenance_type: str,
        scheduled_at: datetime,
        description: str,
        work_order_number: Optional[str] = None,
        assigned_to_id: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        work_performed: Optional[str] = None,
        labor_hours: Optional[float] = None,
        labor_cost: Optional[float] = None,
        parts_cost: Optional[float] = None,
        result: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> MaintenanceRecord:
        """Create a new maintenance record."""
        self._validate_dates(scheduled_at, completed_at)
        await self._lock_and_validate_asset(
            asset_id, maintenance_start=scheduled_at, maintenance_end=completed_at
        )
        if completed_at is not None and not (work_performed or "").strip():
            raise BadRequestError(
                message="Work performed is required for completed maintenance"
            )
        
        record = MaintenanceRecord(
            id=self.generate_id(),
            asset_id=asset_id,
            maintenance_type=maintenance_type,
            scheduled_at=scheduled_at,
            description=description,
            work_order_number=work_order_number,
            assigned_to_id=assigned_to_id,
            completed_at=completed_at,
            work_performed=work_performed,
            labor_hours=labor_hours,
            labor_cost=labor_cost,
            parts_cost=parts_cost,
            result=result,
            notes=notes,
        )
        
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        
        return record
    
    async def update(
        self,
        record_id: str,
        **kwargs,
    ) -> MaintenanceRecord:
        """Update a maintenance record."""
        record = await self.get_by_id(record_id)
        if not record:
            raise NotFoundError(resource="Maintenance Record", resource_id=record_id)
        
        scheduled_at = kwargs.get("scheduled_at") or record.scheduled_at
        completed_at = kwargs.get("completed_at") or record.completed_at
        next_due = kwargs.get("next_maintenance_due") or record.next_maintenance_due
        self._validate_dates(scheduled_at, completed_at, next_due)
        await self._lock_and_validate_asset(
            record.asset_id,
            exclude_record_id=record.id,
            maintenance_start=scheduled_at,
            maintenance_end=completed_at,
        )
        if completed_at is not None:
            work_performed = kwargs.get("work_performed") or record.work_performed
            if not (work_performed or "").strip():
                raise BadRequestError(
                    message="Work performed is required for completed maintenance"
                )

        for key, value in kwargs.items():
            if value is not None and hasattr(record, key):
                setattr(record, key, value)
        
        await self.db.commit()
        await self.db.refresh(record)
        
        return record
    
    async def complete(
        self,
        record_id: str,
        completed_by_id: str,
        work_performed: str,
        parts_used: Optional[str] = None,
        labor_hours: Optional[float] = None,
        labor_cost: Optional[float] = None,
        parts_cost: Optional[float] = None,
        result: Optional[str] = None,
        next_maintenance_due: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> MaintenanceRecord:
        """Complete a maintenance record."""
        record = await self.get_by_id(record_id)
        if not record:
            raise NotFoundError(resource="Maintenance Record", resource_id=record_id)
        
        if record.completed_at:
            raise BadRequestError(message="Maintenance record is already completed")
        
        completed_at = datetime.utcnow()
        self._validate_dates(record.scheduled_at, completed_at, next_maintenance_due)
        await self._lock_and_validate_asset(record.asset_id)
        if not (work_performed or "").strip():
            raise BadRequestError(message="Work performed is required to complete maintenance")

        record.completed_at = completed_at
        record.completed_by_id = completed_by_id
        record.work_performed = work_performed
        record.parts_used = parts_used
        record.labor_hours = labor_hours
        record.labor_cost = labor_cost
        record.parts_cost = parts_cost
        record.result = result
        record.next_maintenance_due = next_maintenance_due
        record.notes = notes
        
        await self.db.commit()
        await self.db.refresh(record)
        
        return record
    
    async def delete(self, record_id: str) -> bool:
        """Delete a maintenance record."""
        record = await self.get_by_id(record_id)
        if not record:
            raise NotFoundError(resource="Maintenance Record", resource_id=record_id)
        
        await self.db.delete(record)
        await self.db.commit()
        
        return True
