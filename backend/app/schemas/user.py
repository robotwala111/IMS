"""
User Schemas

Pydantic models for user CRUD operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole


ASSIGNABLE_USER_ROLES = {
    UserRole.ADMIN,
    UserRole.HEAD_OFFICE_MANAGER,
    UserRole.LOCATION_MANAGER,
}


class UserBase(BaseModel):
    """Base user fields."""
    
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    department: Optional[str] = Field(None, max_length=100)


class UserCreate(UserBase):
    """User creation schema."""
    
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.LOCATION_MANAGER
    assigned_location_ids: List[str] = []
    is_active: bool = True

    @field_validator("role")
    @classmethod
    def role_must_be_active_business_role(cls, value: UserRole) -> UserRole:
        if value not in ASSIGNABLE_USER_ROLES:
            raise ValueError("Only Admin, General Manager, and Location Manager roles are allowed")
        return value


class UserUpdate(BaseModel):
    """User update schema (all fields optional)."""
    
    email: Optional[EmailStr] = None
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    department: Optional[str] = Field(None, max_length=100)
    role: Optional[UserRole] = None
    password: Optional[str] = Field(None, min_length=8)
    assigned_location_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def role_must_be_active_business_role(cls, value: Optional[UserRole]) -> Optional[UserRole]:
        if value is not None and value not in ASSIGNABLE_USER_ROLES:
            raise ValueError("Only Admin, General Manager, and Location Manager roles are allowed")
        return value


class UserResponse(BaseModel):
    """User response schema."""
    
    id: str
    email: str
    name: str
    role: UserRole
    is_active: bool
    phone: Optional[str]
    department: Optional[str]
    assigned_location_ids: List[str]
    last_login_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
    
    @classmethod
    def from_orm_with_locations(cls, user) -> "UserResponse":
        """Create response from ORM model with location IDs."""
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            is_active=user.is_active,
            phone=user.phone,
            department=user.department,
            assigned_location_ids=[loc.id for loc in user.assigned_locations],
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserListResponse(BaseModel):
    """Paginated user list response."""
    
    items: List[UserResponse]
    total: int
    page: int
    page_size: int
    pages: int


class UserProfileUpdate(BaseModel):
    """User self-update (limited fields)."""
    
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
