"""
Calibration Record Model

SQLAlchemy model for asset calibration records.
"""

from datetime import datetime, date
from typing import Optional

from sqlalchemy import String, Text, Date, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CalibrationRecord(Base):
    """Calibration record for serialized assets."""
    
    __tablename__ = "calibration_records"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("serialized_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_by_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Certificate info
    certificate_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    performed_at: Mapped[date] = mapped_column(Date, nullable=False)
    due_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    
    # Calibration details
    performed_by: Mapped[str] = mapped_column(String(255), nullable=False)  # Person/technician name
    calibration_lab: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    calibration_procedure: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Results
    result: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pass",
    )  # pass, fail, limited
    as_found_condition: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    as_left_condition: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    measurements: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    
    # Attachments
    attachment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("attachments.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamps
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
    
    # Relationships
    asset = relationship("SerializedAsset", back_populates="calibration_records")
    recorded_by = relationship("User", foreign_keys=[recorded_by_id])
    
    @property
    def is_expired(self) -> bool:
        """Check if calibration is expired."""
        return self.due_at < date.today()
    
    @property
    def days_until_due(self) -> int:
        """Get days until calibration is due (negative if expired)."""
        return (self.due_at - date.today()).days
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        certificate_number = self.__dict__.get("certificate_number", "<unloaded>")
        due_at = self.__dict__.get("due_at", "<unloaded>")
        return f"<CalibrationRecord(id={id_}, certificate={certificate_number}, due_at={due_at})>"


class CalibrationSupplierTransaction(Base):
    """Supplier send/receive transaction for instrument calibration."""

    __tablename__ = "calibration_supplier_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("serialized_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sent_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    received_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    asset = relationship("SerializedAsset")
    recorded_by = relationship("User", foreign_keys=[recorded_by_id])
