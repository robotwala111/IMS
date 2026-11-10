"""
Employee Record Endpoints

CRUD operations for employee digital records.
"""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_any_role,
    require_manager_or_admin,
    require_admin,
    require_location_access,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.models.employee_record import EmployeeRecordType
from app.schemas.common import MessageResponse
from app.schemas.employee_record import (
    EmployeeRecordCreate,
    EmployeeRecordListResponse,
    EmployeeRecordResponse,
    EmployeeRecordUpdate,
)
from app.services.audit_service import AuditService
from app.services.employee_record_service import EmployeeRecordService
from app.services.employee_service import EmployeeService
from app.services.user_service import UserService

router = APIRouter()


def _require_person_access(current_user, user=None, employee=None) -> None:
    if current_user.has_all_location_access:
        return
    if employee is not None:
        require_location_access(current_user, employee.location_id)
        return
    if user is not None and any(
        current_user.has_location_access(location.id)
        for location in user.assigned_locations
    ):
        return
    raise NotFoundError(resource="Personnel record")


def _require_record_access(current_user, record) -> None:
    _require_person_access(
        current_user,
        user=record.user,
        employee=record.employee,
    )


@router.get("", response_model=EmployeeRecordListResponse)
async def list_employee_records(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    user_id: Optional[str] = Query(None),
    record_type: Optional[EmployeeRecordType] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    _: None = Depends(require_any_role),
) -> EmployeeRecordListResponse:
    service = EmployeeRecordService(db)

    # Filter by user's assigned locations if not admin/head office
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]

    records, total = await service.list_records(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        user_id=user_id,
        record_type=record_type,
        is_active=is_active,
        search=search,
        location_ids=location_ids,
    )

    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]

    return EmployeeRecordListResponse(
        items=records,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/{record_id}", response_model=EmployeeRecordResponse)
async def get_employee_record(
    record_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_any_role),
) -> EmployeeRecordResponse:
    service = EmployeeRecordService(db)
    record = await service.get_by_id(record_id)
    if not record:
        raise NotFoundError(resource="Employee record", resource_id=record_id)
    _require_record_access(current_user, record)
    return record


@router.post("", response_model=EmployeeRecordResponse, status_code=201)
async def create_employee_record(
    request: EmployeeRecordCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> EmployeeRecordResponse:
    service = EmployeeRecordService(db)
    user_service = UserService(db)
    employee_service = EmployeeService(db)
    audit_service = AuditService(db)

    # Validate that exactly one of user_id or employee_id is provided
    if not request.user_id and not request.employee_id:
        raise ValidationError("Either user_id or employee_id must be provided")
    if request.user_id and request.employee_id:
        raise ValidationError("Provide only one of user_id or employee_id, not both")

    if request.user_id:
        user = await user_service.get_by_id(request.user_id)
        if not user:
            raise NotFoundError(resource="User", resource_id=request.user_id)
        if not user.is_active:
            raise ValidationError("Personnel records cannot be assigned to an inactive user")
        _require_person_access(current_user, user=user)
    else:
        employee = await employee_service.get_by_id(request.employee_id)
        if not employee:
            raise NotFoundError(resource="Employee", resource_id=request.employee_id)
        if not employee.is_active:
            raise ValidationError("Personnel records cannot be assigned to an inactive employee")
        _require_person_access(current_user, employee=employee)

    payload = request.model_dump()
    if (
        payload.get("record_type") == EmployeeRecordType.VISION_CERTIFICATE
        and payload.get("issue_date")
        and not payload.get("expiry_date")
    ):
        payload["expiry_date"] = payload["issue_date"] + timedelta(days=90)

    await service.ensure_not_duplicate(
        user_id=payload.get("user_id"), employee_id=payload.get("employee_id"),
        record_type=payload["record_type"], title=payload["title"],
        certificate_number=payload.get("certificate_number"), issuer=payload.get("issuer"),
    )

    record = await service.create(**payload)

    await audit_service.log_action(
        action="create",
        resource_type="employee_record",
        resource_id=record.id,
        user_id=current_user.id,
        new_value={
            "user_id": record.user_id,
            "employee_id": record.employee_id,
            "record_type": record.record_type.value,
            "title": record.title,
        },
    )

    return await service.get_by_id(record.id)


@router.patch("/{record_id}", response_model=EmployeeRecordResponse)
async def update_employee_record(
    record_id: str,
    request: EmployeeRecordUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> EmployeeRecordResponse:
    service = EmployeeRecordService(db)
    user_service = UserService(db)
    employee_service = EmployeeService(db)
    audit_service = AuditService(db)

    existing = await service.get_by_id(record_id)
    if not existing:
        raise NotFoundError(resource="Employee record", resource_id=record_id)
    _require_record_access(current_user, existing)

    update_data = request.model_dump(exclude_unset=True)
    if update_data.get("revoked_at"):
        if not (update_data.get("revocation_reason") or "").strip():
            raise ValidationError("A revocation reason is required")
        update_data["is_active"] = False
    if update_data.get("is_active") is True and existing.revoked_at:
        raise ValidationError("A revoked personnel record cannot be reactivated")

    owner_fields_supplied = "user_id" in update_data or "employee_id" in update_data
    requested_user_id = update_data.get("user_id")
    requested_employee_id = update_data.get("employee_id")
    if owner_fields_supplied and bool(requested_user_id) == bool(requested_employee_id):
        raise ValidationError("Provide exactly one of user_id or employee_id")

    if requested_user_id:
        user = await user_service.get_by_id(requested_user_id)
        if not user:
            raise NotFoundError(resource="User", resource_id=requested_user_id)
        if not user.is_active:
            raise ValidationError("Personnel records cannot be assigned to an inactive user")
        _require_person_access(current_user, user=user)
        update_data["employee_id"] = None
    elif requested_employee_id:
        employee = await employee_service.get_by_id(requested_employee_id)
        if not employee:
            raise NotFoundError(resource="Employee", resource_id=requested_employee_id)
        if not employee.is_active:
            raise ValidationError("Personnel records cannot be assigned to an inactive employee")
        _require_person_access(current_user, employee=employee)
        update_data["user_id"] = None

    effective_record_type = update_data.get("record_type", existing.record_type)
    effective_issue_date = update_data.get("issue_date", existing.issue_date)
    effective_expiry_date = update_data.get("expiry_date", existing.expiry_date)
    if (
        effective_record_type == EmployeeRecordType.VISION_CERTIFICATE
        and effective_issue_date
        and not effective_expiry_date
    ):
        update_data["expiry_date"] = effective_issue_date + timedelta(days=90)
        effective_expiry_date = update_data["expiry_date"]

    if effective_issue_date and effective_expiry_date and effective_expiry_date < effective_issue_date:
        raise ValidationError("Expiry date cannot be before issue date")

    await service.ensure_not_duplicate(
        user_id=requested_user_id if owner_fields_supplied else existing.user_id,
        employee_id=requested_employee_id if owner_fields_supplied else existing.employee_id,
        record_type=effective_record_type,
        title=update_data.get("title", existing.title),
        certificate_number=update_data.get("certificate_number", existing.certificate_number),
        issuer=update_data.get("issuer", existing.issuer), exclude_id=existing.id,
    )

    old_value = {
        "user_id": existing.user_id,
        "record_type": existing.record_type.value,
        "title": existing.title,
        "is_active": existing.is_active,
    }

    record = await service.update(record_id, **update_data)

    await audit_service.log_action(
        action="update",
        resource_type="employee_record",
        resource_id=record.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value={
            "user_id": record.user_id,
            "record_type": record.record_type.value,
            "title": record.title,
            "is_active": record.is_active,
        },
    )

    return await service.get_by_id(record.id)


@router.delete("/{record_id}", response_model=MessageResponse)
async def delete_employee_record(
    record_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    service = EmployeeRecordService(db)
    audit_service = AuditService(db)

    record = await service.get_by_id(record_id)
    if not record:
        raise NotFoundError(resource="Employee record", resource_id=record_id)
    _require_record_access(current_user, record)

    await service.delete(record_id)

    await audit_service.log_action(
        action="delete",
        resource_type="employee_record",
        resource_id=record_id,
        user_id=current_user.id,
        old_value={
            "user_id": record.user_id,
            "record_type": record.record_type.value,
            "title": record.title,
        },
    )

    return MessageResponse(message="Employee record deleted successfully")
