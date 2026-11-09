"""
Job Model

Defines jobs (hold) for tracking NDT work assignments and completion.
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.location import Location


class JobStatus(str, enum.Enum):
    """Status of a job."""

    HOLD = "hold"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VERIFIED = "verified"


class JobMethod(str, enum.Enum):
    """NDT inspection method."""

    RT = "rt"          # Radiographic Testing
    UT = "ut"          # Ultrasonic Testing
    MT = "mt"          # Magnetic Particle Testing
    PT = "pt"          # Penetrant Testing
    VT = "vt"          # Visual Testing
    ET = "et"          # Eddy Current Testing
    OTHER = "other"


class Job(Base):
    """Job (Hold) record."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    # Auto-generated job number
    job_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )

    # Core fields
    job_date: Mapped[date] = mapped_column(Date, nullable=False)
    customer: Mapped[str] = mapped_column(String(255), nullable=False)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(50), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    coverage: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Assigned person
    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_to_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    # Location (for RBAC)
    location_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True, index=True
    )

    # Status
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus),
        default=JobStatus.HOLD,
        nullable=False,
        index=True,
    )

    # Completion fields (filled when person marks job as "done")
    completed_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Result breakdown
    accepted: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reshoot: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cut_films: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True
    )  # Flexible text/JSON – user enters details
    cut_films_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Whether this job's completion has been validated so new jobs can be issued
    is_validated: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    # Audit: who created the record
    created_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    # ---- Relationships ----
    assigned_to: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[assigned_to_id]
    )
    completed_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[completed_by_id]
    )
    created_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by_id]
    )
    location: Mapped[Optional["Location"]] = relationship("Location")

    # ---- Computed properties for API serialization ----

    @property
    def assigned_to_name(self) -> Optional[str]:
        return self.assigned_to.name if self.assigned_to else None

    @property
    def completed_by_name(self) -> Optional[str]:
        return self.completed_by.name if self.completed_by else None

    @property
    def created_by_name(self) -> Optional[str]:
        return self.created_by.name if self.created_by else None

    @property
    def location_name(self) -> Optional[str]:
        return self.location.name if self.location else None

    @property
    def completion_total(self) -> int:
        """Sum of accepted + reshoot + cut_films numeric portion."""
        a = self.accepted or 0
        r = self.reshoot or 0
        c = self.cut_films_count or 0
        return a + r + c

    @property
    def is_completion_balanced(self) -> bool:
        """True when accepted + reshoot + cut_films == total."""
        return self.completion_total == self.total

    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        job_number = self.__dict__.get("job_number", "<unloaded>")
        status = self.__dict__.get("status", "<unloaded>")
        return f"<Job(id={id_}, number={job_number}, status={status})>"
