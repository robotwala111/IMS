"""
Employee Record Schemas

Pydantic models for employee digital records.
"""

from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.employee_record import EmployeeRecordType


class EmployeeRecordBase(BaseModel):
    """Base employee record schema."""

    # One of user_id or employee_id is required (validated in the endpoint)
    user_id: Optional[str] = None
    employee_id: Optional[str] = None
    record_type: EmployeeRecordType
    title: str = Field(..., min_length=1, max_length=255)
    certificate_number: Optional[str] = Field(None, max_length=100)
    issuer: Optional[str] = Field(None, max_length=255)
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None
    is_active: bool = True

    @model_validator(mode="after")
    def validate_dates(self):
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("Expiry date cannot be before issue date")
        if bool(self.revoked_at) != bool((self.revocation_reason or "").strip()):
            raise ValueError("Revocation date and reason must be provided together")
        if self.revoked_at:
            self.is_active = False
        return self


class EmployeeRecordCreate(EmployeeRecordBase):
    """Create employee record schema."""


class EmployeeRecordUpdate(BaseModel):
    """Update employee record schema."""

    user_id: Optional[str] = None
    employee_id: Optional[str] = None
    record_type: Optional[EmployeeRecordType] = None
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    certificate_number: Optional[str] = Field(None, max_length=100)
    issuer: Optional[str] = Field(None, max_length=255)
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None
    is_active: Optional[bool] = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.issue_date and self.expiry_date and self.expiry_date < self.issue_date:
            raise ValueError("Expiry date cannot be before issue date")
        if self.revoked_at and not (self.revocation_reason or "").strip():
            raise ValueError("A revocation reason is required")
        return self


class EmployeeRecordResponse(BaseModel):
    """Employee record response schema."""

    id: str
    user_id: Optional[str] = None
    employee_id: Optional[str] = None
    user_name: Optional[str] = None
    employee_name: Optional[str] = None
    record_type: EmployeeRecordType
    title: str
    certificate_number: Optional[str]
    issuer: Optional[str]
    issue_date: Optional[date]
    expiry_date: Optional[date]
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None
    notes: Optional[str]
    is_active: bool
    user_location: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def populate_computed_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return value

        user = getattr(value, "user", None)
        employee = getattr(value, "employee", None)

        # Resolve display name
        user_name = getattr(user, "name", None) if user else None
        employee_name = getattr(employee, "name", None) if employee else None

        # Resolve location: from user's assigned_locations, then from employee.location
        user_location = None
        if user:
            locs = getattr(user, "assigned_locations", None) or []
            if locs:
                user_location = getattr(locs[0], "name", None)
        if not user_location and employee:
            loc = getattr(employee, "location", None)
            if loc:
                user_location = getattr(loc, "name", None)

        return {
            "id": getattr(value, "id", None),
            "user_id": getattr(value, "user_id", None),
            "employee_id": getattr(value, "employee_id", None),
            "user_name": user_name,
            "employee_name": employee_name,
            "user_location": user_location,
            "record_type": getattr(value, "record_type", None),
            "title": getattr(value, "title", None),
            "certificate_number": getattr(value, "certificate_number", None),
            "issuer": getattr(value, "issuer", None),
            "issue_date": getattr(value, "issue_date", None),
            "expiry_date": getattr(value, "expiry_date", None),
            "revoked_at": getattr(value, "revoked_at", None),
            "revocation_reason": getattr(value, "revocation_reason", None),
            "notes": getattr(value, "notes", None),
            "is_active": getattr(value, "is_active", True),
            "created_at": getattr(value, "created_at", None),
            "updated_at": getattr(value, "updated_at", None),
        }


class EmployeeRecordListResponse(BaseModel):
    """Paginated employee record list response."""

    items: List[EmployeeRecordResponse]
    total: int
    page: int
    page_size: int
    pages: int
