"""
Employee Schemas

Pydantic models for non-login employee management.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EmployeeBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    employee_code: Optional[str] = Field(None, max_length=50)
    designation: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    location_id: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    employee_code: Optional[str] = Field(None, max_length=50)
    designation: Optional[str] = Field(None, max_length=100)
    department: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    location_id: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class EmployeeResponse(BaseModel):
    id: str
    name: str
    employee_code: Optional[str]
    designation: Optional[str]
    department: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    location_id: Optional[str]
    location_name: Optional[str] = None
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmployeeListResponse(BaseModel):
    items: List[EmployeeResponse]
    total: int
    page: int
    page_size: int
    pages: int
