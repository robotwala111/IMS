"""
Authentication Schemas

Pydantic models for authentication requests and responses.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import UserRole


ASSIGNABLE_USER_ROLES = {
    UserRole.ADMIN,
    UserRole.HEAD_OFFICE_MANAGER,
    UserRole.LOCATION_MANAGER,
}


class LoginRequest(BaseModel):
    """Login request payload."""
    
    email: EmailStr
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Login response with tokens."""
    
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    user: "UserBasicInfo"


class UserBasicInfo(BaseModel):
    """Basic user info included in auth responses."""
    
    id: str
    email: str
    name: str
    role: UserRole
    assigned_location_ids: List[str]
    last_login_at: Optional[datetime] = None
    
    model_config = {"from_attributes": True}


class TokenRefreshRequest(BaseModel):
    """Token refresh request."""
    
    refresh_token: str


class TokenRefreshResponse(BaseModel):
    """Token refresh response."""
    
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    """Change password request."""
    
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)


class RegisterRequest(BaseModel):
    """User registration request (admin only)."""
    
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8)
    role: UserRole = UserRole.LOCATION_MANAGER
    assigned_location_ids: List[str] = []
    phone: Optional[str] = None
    department: Optional[str] = None

    @field_validator("role")
    @classmethod
    def role_must_be_active_business_role(cls, value: UserRole) -> UserRole:
        if value not in ASSIGNABLE_USER_ROLES:
            raise ValueError("Only Admin, General Manager, and Location Manager roles are allowed")
        return value


class ForgotPasswordRequest(BaseModel):
    """Forgot password request."""
    
    email: EmailStr


class PasswordResetRequest(BaseModel):
    """Consume a single-use password reset token."""

    token: str = Field(..., min_length=20)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)


class TokenPayload(BaseModel):
    """JWT token payload."""
    
    sub: str  # user_id
    exp: datetime
    iat: datetime
    type: str  # "access" or "refresh"
    role: Optional[str] = None
    email: Optional[str] = None
