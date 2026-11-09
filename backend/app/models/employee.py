"""
Employee Model

Represents any employee / field technician who should have their
personnel records managed in the system.  An Employee does NOT
require a login account — they are distinct from the User model
which is for system access only.

Relationship:
  Employee  →  EmployeeRecord (one-to-many)
  User      →  EmployeeRecord (one-to-many, for users who also have accounts)
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee_record import EmployeeRecord
    from app.models.location import Location


class Employee(Base):
    """Non-login employee whose records are managed by location staff."""

    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    employee_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, unique=True, index=True)
    designation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    department: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Primary location this employee is associated with
    location_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True, index=True
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    location: Mapped[Optional["Location"]] = relationship("Location")
    records: Mapped[List["EmployeeRecord"]] = relationship(
        "EmployeeRecord",
        back_populates="employee",
        cascade="all, delete-orphan",
        foreign_keys="EmployeeRecord.employee_id",
    )

    @property
    def location_name(self) -> Optional[str]:
        return self.location.name if self.location else None

    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        name = self.__dict__.get("name", "<unloaded>")
        return f"<Employee(id={id_}, name={name})>"
