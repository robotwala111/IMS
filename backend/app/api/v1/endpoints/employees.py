"""
Employee Endpoints

CRUD for non-login employees (field technicians, site workers, etc.)
who don't have system login accounts but whose personnel records must be managed.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_any_role,
    require_manager_or_admin,
    require_admin,
    authorized_location_ids,
    require_location_access,
)
from app.core.exceptions import NotFoundError
from app.schemas.common import MessageResponse
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeListResponse,
    EmployeeResponse,
    EmployeeUpdate,
)
from app.services.audit_service import AuditService
from app.services.employee_service import EmployeeService

router = APIRouter()


@router.get("", response_model=EmployeeListResponse)
async def list_employees(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    search: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    _: None = Depends(require_any_role),
) -> EmployeeListResponse:
    service = EmployeeService(db)

    allowed_location_ids = authorized_location_ids(current_user)
    if location_id and allowed_location_ids is not None:
        require_location_access(current_user, location_id)

    employees, total = await service.list_employees(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination.get("sort_by", "name"),
        sort_order=pagination.get("sort_order", "asc"),
        search=search,
        location_id=location_id,
        location_ids=allowed_location_ids,
        is_active=is_active,
    )

    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]

    return EmployeeListResponse(
        items=employees,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_any_role),
) -> EmployeeResponse:
    service = EmployeeService(db)
    employee = await service.get_by_id(employee_id)
    if not employee:
        raise NotFoundError(resource="Employee", resource_id=employee_id)
    require_location_access(current_user, employee.location_id)
    return employee


@router.post("", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    request: EmployeeCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> EmployeeResponse:
    service = EmployeeService(db)
    audit_service = AuditService(db)

    require_location_access(current_user, request.location_id)
    employee = await service.create_employee(request.model_dump())

    await audit_service.log_action(
        action="create",
        resource_type="employee",
        resource_id=employee.id,
        user_id=current_user.id,
        new_value={"name": employee.name, "location_id": employee.location_id},
    )

    employee = await service.get_by_id(employee.id)
    return employee


@router.patch("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: str,
    request: EmployeeUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> EmployeeResponse:
    service = EmployeeService(db)
    audit_service = AuditService(db)

    employee = await service.get_by_id(employee_id)
    if not employee:
        raise NotFoundError(resource="Employee", resource_id=employee_id)
    require_location_access(current_user, employee.location_id)

    old_value = {"name": employee.name, "is_active": employee.is_active}
    update_data = request.model_dump(exclude_unset=True)
    if "location_id" in update_data:
        require_location_access(current_user, update_data["location_id"])

    employee = await service.update_employee(employee, update_data)

    await audit_service.log_action(
        action="update",
        resource_type="employee",
        resource_id=employee.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value={"name": employee.name, "is_active": employee.is_active},
    )

    employee = await service.get_by_id(employee.id)
    return employee


@router.delete("/{employee_id}", response_model=MessageResponse)
async def delete_employee(
    employee_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    service = EmployeeService(db)
    audit_service = AuditService(db)

    employee = await service.get_by_id(employee_id)
    if not employee:
        raise NotFoundError(resource="Employee", resource_id=employee_id)
    require_location_access(current_user, employee.location_id)

    await service.delete(employee_id)

    await audit_service.log_action(
        action="delete",
        resource_type="employee",
        resource_id=employee_id,
        user_id=current_user.id,
        old_value={"name": employee.name},
    )

    return MessageResponse(message="Employee deleted successfully")
