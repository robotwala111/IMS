"""
Employee Service

Business logic for managing non-login employees.
"""

import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.models.employee import Employee
from app.models.location import Location
from app.services.base_service import BaseService


class EmployeeService(BaseService[Employee]):
    """Service for employee management."""

    @property
    def model(self):
        return Employee

    async def get_by_id(self, id: str) -> Optional[Employee]:
        result = await self.db.execute(
            select(Employee)
            .options(selectinload(Employee.location))
            .where(Employee.id == id)
        )
        return result.scalar_one_or_none()

    async def list_employees(
        self,
        page: int = 1,
        page_size: int = 50,
        sort_by: str = "name",
        sort_order: str = "asc",
        search: Optional[str] = None,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[Employee], int]:
        query = select(Employee).options(selectinload(Employee.location))

        if location_ids is not None:
            query = query.where(Employee.location_id.in_(location_ids))

        if location_id:
            query = query.where(Employee.location_id == location_id)

        if is_active is not None:
            query = query.where(Employee.is_active == is_active)

        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    Employee.name.ilike(pattern),
                    Employee.employee_code.ilike(pattern),
                    Employee.designation.ilike(pattern),
                    Employee.department.ilike(pattern),
                    Employee.phone.ilike(pattern),
                )
            )

        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        col = getattr(Employee, sort_by, Employee.name)
        query = query.order_by(col.desc() if sort_order == "desc" else col.asc())
        query = query.offset((page - 1) * page_size).limit(page_size)

        rows = await self.db.execute(query)
        return list(rows.scalars().unique().all()), total

    async def create_employee(self, data: dict) -> Employee:
        employee = Employee(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            **data,
        )
        self.db.add(employee)
        await self.db.flush()
        await self.db.refresh(employee)
        # reload with location
        return await self.get_by_id(employee.id)

    async def update_employee(self, employee: Employee, data: dict) -> Employee:
        for key, value in data.items():
            if value is not None or key in data:
                setattr(employee, key, value)
        employee.updated_at = datetime.utcnow()
        await self.db.flush()
        return await self.get_by_id(employee.id)
