"""
Employee Record Model

Stores digital personnel records for employees.
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.employee import Employee
    from app.models.user import User


class EmployeeRecordType(str, enum.Enum):
    """Supported personnel evaluation record types."""

    PERSONAL_QUALIFICATION = "personal_qualification"
    PERSONAL_EXPERIENCE = "personal_experience"
    VISION_CERTIFICATE = "vision_certificate"


class EmployeeRecord(Base):
    """Digital personnel record for an employee."""

    __tablename__ = "employee_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # One of user_id or employee_id must be set.
    # user_id  — links to a system User account
    # employee_id — links to a non-login Employee record
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    employee_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    record_type: Mapped[EmployeeRecordType] = mapped_column(
        Enum(EmployeeRecordType),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    certificate_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    issuer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id])
    employee: Mapped[Optional["Employee"]] = relationship(
        "Employee", back_populates="records", foreign_keys=[employee_id]
    )

    @property
    def person_name(self) -> Optional[str]:
        """Name of the person this record belongs to (user or employee)."""
        if self.user:
            return self.user.name
        if self.employee:
            return self.employee.name
        return None

    # Keep user_name as alias for backwards compat
    @property
    def user_name(self) -> Optional[str]:
        return self.person_name

    @property
    def employee_name(self) -> Optional[str]:
        """Name of the non-login employee (if this record is for a non-login employee)."""
        return self.employee.name if self.employee else None

    @property
    def user_location(self) -> Optional[str]:
        """Comma-separated location names for this person."""
        if self.user and hasattr(self.user, 'assigned_locations') and self.user.assigned_locations:
            return ', '.join(loc.name for loc in self.user.assigned_locations)
        if self.employee and self.employee.location:
            return self.employee.location.name
        return None

    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        record_type = self.__dict__.get("record_type", "<unloaded>")
        user_id = self.__dict__.get("user_id", "<unloaded>")
        return f"<EmployeeRecord(id={id_}, type={record_type}, user_id={user_id})>"
