"""
User Model

Defines the User entity with role-based access control.
"""

import enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Enum, ForeignKey, String, Table, Column
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.location import Location


class UserRole(str, enum.Enum):
    """User roles for RBAC."""
    
    ADMIN = "admin"
    HEAD_OFFICE_MANAGER = "head_office_manager"
    LOCATION_MANAGER = "location_manager"


# Association table for user-location assignments
user_location_association = Table(
    "user_locations",
    Base.metadata,
    Column("user_id", String(36), ForeignKey("users.id"), primary_key=True),
    Column("location_id", String(36), ForeignKey("locations.id"), primary_key=True),
)


class User(Base):
    """User model for authentication and authorization."""
    
    __tablename__ = "users"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole),
        default=UserRole.LOCATION_MANAGER,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Optional profile fields
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Security tracking
    failed_login_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    last_login_at: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Relationships
    assigned_locations: Mapped[List["Location"]] = relationship(
        "Location",
        secondary=user_location_association,
        back_populates="assigned_users",
    )
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        email = self.__dict__.get("email", "<unloaded>")
        role = self.__dict__.get("role", "<unloaded>")
        return f"<User(id={id_}, email={email}, role={role})>"
    
    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN
    
    @property
    def is_head_office_manager(self) -> bool:
        """Check if user has head office manager role."""
        return self.role == UserRole.HEAD_OFFICE_MANAGER
    
    @property
    def is_location_manager(self) -> bool:
        """Check if user has location manager role."""
        return self.role == UserRole.LOCATION_MANAGER
    
    @property
    def is_manager(self) -> bool:
        """Check if user has any manager role."""
        return self.role in (UserRole.HEAD_OFFICE_MANAGER, UserRole.LOCATION_MANAGER)
    
    @property
    def has_all_location_access(self) -> bool:
        """Check if user can access all locations (admin or head office manager)."""
        return self.role in (UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER)
    
    def has_location_access(self, location_id: str) -> bool:
        """Check if user has access to a specific location."""
        if self.has_all_location_access:
            return True
        return any(loc.id == location_id for loc in self.assigned_locations)
