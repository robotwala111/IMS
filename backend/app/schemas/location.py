"""
Location Schemas

Pydantic models for location CRUD operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LocationBase(BaseModel):
    """Base location fields."""
    
    code: str = Field(..., min_length=2, max_length=20)
    name: str = Field(..., min_length=2, max_length=255)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    contact_person: Optional[str] = Field(None, max_length=255)


class LocationCreate(LocationBase):
    """Location creation schema."""
    
    is_active: bool = True


class LocationUpdate(BaseModel):
    """Location update schema (all fields optional)."""
    
    code: Optional[str] = Field(None, min_length=2, max_length=20)
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    address: Optional[str] = None
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    country: Optional[str] = Field(None, max_length=100)
    postal_code: Optional[str] = Field(None, max_length=20)
    phone: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=255)
    contact_person: Optional[str] = Field(None, max_length=255)
    is_active: Optional[bool] = None


class LocationAssignedUser(BaseModel):
    """Brief user info for location cards."""
    id: str
    name: str
    email: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class LocationResponse(BaseModel):
    """Location response schema."""
    
    id: str
    code: str
    name: str
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    postal_code: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    contact_person: Optional[str]
    is_active: bool
    assigned_users: List[LocationAssignedUser] = []
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class LocationListResponse(BaseModel):
    """Paginated location list response."""
    
    items: List[LocationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class LocationSummary(BaseModel):
    """Brief location info for dropdowns."""
    
    id: str
    code: str
    name: str
    
    model_config = ConfigDict(from_attributes=True)
