"""
Calibration Service

Handles calibration record management for serialized assets.
"""

from datetime import datetime, date, timedelta
from typing import Optional, List, Tuple

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.calibration import CalibrationRecord
from app.models.asset import SerializedAsset
from app.services.base_service import BaseService


class CalibrationService(BaseService[CalibrationRecord]):
    """Service for calibration record management."""
    
    @property
    def model(self):
        return CalibrationRecord
    
    async def get_by_id(self, id: str) -> Optional[CalibrationRecord]:
        """Get calibration record with related data."""
        result = await self.db.execute(
            select(CalibrationRecord)
            .options(
                selectinload(CalibrationRecord.asset).selectinload(SerializedAsset.location),
                selectinload(CalibrationRecord.recorded_by),
            )
            .where(CalibrationRecord.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_certificate_number(self, certificate_number: str) -> Optional[CalibrationRecord]:
        """Get calibration record by certificate number."""
        result = await self.db.execute(
            select(CalibrationRecord).where(
                func.lower(CalibrationRecord.certificate_number)
                == certificate_number.strip().lower()
            )
        )
        return result.scalar_one_or_none()
    
    async def list_records(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "due_at",
        sort_order: str = "asc",
        asset_id: Optional[str] = None,
        location_id: Optional[str] = None,
        due_before: Optional[date] = None,
        expired_only: bool = False,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[List[CalibrationRecord], int]:
        """
        List calibration records with filtering.
        
        Returns:
            Tuple of (records, total_count)
        """
        query = select(CalibrationRecord).options(
            selectinload(CalibrationRecord.asset).selectinload(SerializedAsset.location),
        )
        
        # Join with asset for location filtering
        query = query.join(SerializedAsset)
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        # Apply filters
        if asset_id:
            query = query.where(CalibrationRecord.asset_id == asset_id)
        
        if location_id:
            query = query.where(SerializedAsset.location_id == location_id)
        
        if due_before:
            query = query.where(CalibrationRecord.due_at <= due_before)
        
        if expired_only:
            today = date.today()
            query = query.where(CalibrationRecord.due_at < today)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(CalibrationRecord, sort_by):
            order_column = getattr(CalibrationRecord, sort_by)
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
    ) -> List[CalibrationRecord]:
        """Get calibrations due within specified days."""
        today = date.today()
        due_date = today + timedelta(days=days)
        
        query = (
            select(CalibrationRecord)
            .options(
                selectinload(CalibrationRecord.asset).selectinload(SerializedAsset.location),
            )
            .join(SerializedAsset)
            .where(
                and_(
                    CalibrationRecord.due_at >= today,
                    CalibrationRecord.due_at <= due_date,
                )
            )
        )
        
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        # Only get the latest calibration for each asset
        subquery = (
            select(
                CalibrationRecord.asset_id,
                func.max(CalibrationRecord.performed_at).label("latest")
            )
            .group_by(CalibrationRecord.asset_id)
            .subquery()
        )
        
        query = query.join(
            subquery,
            and_(
                CalibrationRecord.asset_id == subquery.c.asset_id,
                CalibrationRecord.performed_at == subquery.c.latest,
            )
        )
        
        query = query.order_by(CalibrationRecord.due_at.asc())
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def get_expired(
        self,
        location_ids: Optional[List[str]] = None,
    ) -> List[CalibrationRecord]:
        """Get all expired calibrations."""
        today = date.today()
        
        query = (
            select(CalibrationRecord)
            .options(
                selectinload(CalibrationRecord.asset).selectinload(SerializedAsset.location),
            )
            .join(SerializedAsset)
            .where(CalibrationRecord.due_at < today)
        )
        
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        # Only get the latest calibration for each asset
        subquery = (
            select(
                CalibrationRecord.asset_id,
                func.max(CalibrationRecord.performed_at).label("latest")
            )
            .group_by(CalibrationRecord.asset_id)
            .subquery()
        )
        
        query = query.join(
            subquery,
            and_(
                CalibrationRecord.asset_id == subquery.c.asset_id,
                CalibrationRecord.performed_at == subquery.c.latest,
            )
        )
        
        query = query.order_by(CalibrationRecord.due_at.asc())
        
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def get_asset_history(self, asset_id: str) -> List[CalibrationRecord]:
        """Get calibration history for an asset."""
        query = (
            select(CalibrationRecord)
            .options(selectinload(CalibrationRecord.recorded_by))
            .where(CalibrationRecord.asset_id == asset_id)
            .order_by(CalibrationRecord.performed_at.desc())
        )
        
        result = await self.db.execute(query)
        return list(result.scalars().all())
    
    async def create(
        self,
        asset_id: str,
        recorded_by_id: str,
        certificate_number: str,
        performed_at: date,
        due_at: date,
        performed_by: str,
        calibration_lab: Optional[str] = None,
        calibration_procedure: Optional[str] = None,
        result: str = "pass",
        as_found_condition: Optional[str] = None,
        as_left_condition: Optional[str] = None,
        measurements: Optional[str] = None,
        attachment_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> CalibrationRecord:
        """Create a new calibration record."""
        # Validate asset
        asset_result = await self.db.execute(
            select(SerializedAsset).where(SerializedAsset.id == asset_id)
        )
        if not asset_result.scalar_one_or_none():
            raise NotFoundError(resource="Asset", resource_id=asset_id)
        
        record = CalibrationRecord(
            id=self.generate_id(),
            asset_id=asset_id,
            recorded_by_id=recorded_by_id,
            certificate_number=certificate_number,
            performed_at=performed_at,
            due_at=due_at,
            performed_by=performed_by,
            calibration_lab=calibration_lab,
            calibration_procedure=calibration_procedure,
            result=result,
            as_found_condition=as_found_condition,
            as_left_condition=as_left_condition,
            measurements=measurements,
            attachment_id=attachment_id,
            notes=notes,
        )
        
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        
        return record
