"""
Employee Record Service

Business logic for employee digital records.
"""

from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.models.employee_record import EmployeeRecord
from app.models.employee import Employee
from app.models.user import User
from app.core.exceptions import BadRequestError
from app.services.base_service import BaseService


class EmployeeRecordService(BaseService[EmployeeRecord]):
    """Service for employee record management."""

    @property
    def model(self):
        return EmployeeRecord

    async def ensure_not_duplicate(
        self, *, user_id: Optional[str], employee_id: Optional[str], record_type,
        title: str, certificate_number: Optional[str], issuer: Optional[str],
        exclude_id: Optional[str] = None,
    ) -> None:
        owner_filter = (
            EmployeeRecord.user_id == user_id
            if user_id else EmployeeRecord.employee_id == employee_id
        )
        query = select(EmployeeRecord.id).where(
            owner_filter, EmployeeRecord.record_type == record_type,
        )
        certificate_number = (certificate_number or "").strip()
        if certificate_number:
            query = query.where(
                func.lower(func.trim(EmployeeRecord.certificate_number))
                == certificate_number.lower()
            )
        else:
            query = query.where(
                func.lower(func.trim(EmployeeRecord.title)) == title.strip().lower(),
                func.lower(func.trim(func.coalesce(EmployeeRecord.issuer, "")))
                == (issuer or "").strip().lower(),
            )
        if exclude_id:
            query = query.where(EmployeeRecord.id != exclude_id)
        if (await self.db.execute(query.limit(1))).scalar_one_or_none():
            raise BadRequestError(
                message="A matching certificate or qualification already exists for this person"
            )

    async def update(self, id: str, **kwargs) -> Optional[EmployeeRecord]:
        """Update a record, allowing its mutually exclusive owner fields to be cleared."""
        instance = await self.get_by_id(id)
        if not instance:
            return None
        for key, value in kwargs.items():
            if hasattr(instance, key) and (value is not None or key in {"user_id", "employee_id"}):
                setattr(instance, key, value)
        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    async def get_by_id(self, id: str) -> Optional[EmployeeRecord]:
        result = await self.db.execute(
            select(EmployeeRecord)
            .options(
                selectinload(EmployeeRecord.user).selectinload(User.assigned_locations),
                selectinload(EmployeeRecord.employee).selectinload(Employee.location),
            )
            .where(EmployeeRecord.id == id)
        )
        return result.scalar_one_or_none()

    async def list_records(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        user_id: Optional[str] = None,
        record_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[List[EmployeeRecord], int]:
        query = select(EmployeeRecord).options(
            selectinload(EmployeeRecord.user).selectinload(User.assigned_locations),
            selectinload(EmployeeRecord.employee).selectinload(Employee.location),
        )

        # Filter by location: include records where:
        # - the linked user is assigned to one of the given locations, OR
        # - the linked (non-login) employee belongs to one of the given locations
        if location_ids is not None:
            from app.models.user import user_location_association
            user_in_loc = (
                select(EmployeeRecord.id)
                .join(User, EmployeeRecord.user_id == User.id)
                .join(user_location_association, User.id == user_location_association.c.user_id)
                .where(user_location_association.c.location_id.in_(location_ids))
            )
            employee_in_loc = (
                select(EmployeeRecord.id)
                .join(Employee, EmployeeRecord.employee_id == Employee.id)
                .where(Employee.location_id.in_(location_ids))
            )
            query = query.where(
                or_(
                    EmployeeRecord.id.in_(user_in_loc),
                    EmployeeRecord.id.in_(employee_in_loc),
                )
            )

        if user_id:
            query = query.where(EmployeeRecord.user_id == user_id)

        if record_type:
            query = query.where(EmployeeRecord.record_type == record_type)

        if is_active is not None:
            query = query.where(EmployeeRecord.is_active == is_active)

        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    EmployeeRecord.title.ilike(search_pattern),
                    EmployeeRecord.certificate_number.ilike(search_pattern),
                    EmployeeRecord.issuer.ilike(search_pattern),
                    EmployeeRecord.notes.ilike(search_pattern),
                )
            )

        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()

        if hasattr(EmployeeRecord, sort_by):
            order_column = getattr(EmployeeRecord, sort_by)
            query = query.order_by(order_column.desc() if sort_order == "desc" else order_column.asc())

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        items = list(result.scalars().unique().all())

        return items, total
