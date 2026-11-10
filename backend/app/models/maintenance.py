"""
Maintenance Record Model

SQLAlchemy model for asset maintenance records.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class MaintenanceRecord(Base):
    """Maintenance record for serialized assets."""
    
    __tablename__ = "maintenance_records"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("serialized_assets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Type and scheduling
    maintenance_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # preventive, corrective, predictive, emergency
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Work order
    work_order_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    work_performed: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Parts and labor
    parts_used: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    labor_hours: Mapped[Optional[float]] = mapped_column(Numeric(10, 2), nullable=True)
    labor_cost: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    parts_cost: Mapped[Optional[float]] = mapped_column(Numeric(12, 2), nullable=True)
    
    # Assignment
    assigned_to_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    completed_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    
    # Results
    result: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    next_maintenance_due: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
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
    asset = relationship("SerializedAsset", back_populates="maintenance_records")
    assigned_to = relationship("User", foreign_keys=[assigned_to_id])
    completed_by = relationship("User", foreign_keys=[completed_by_id])
    
    @property
    def is_completed(self) -> bool:
        """Check if maintenance is completed."""
        return self.completed_at is not None
    
    @property
    def is_overdue(self) -> bool:
        """Check if maintenance is overdue."""
        if self.completed_at:
            return False
        return self.scheduled_at < datetime.utcnow()
    
    @property
    def total_cost(self) -> Optional[float]:
        """Calculate total cost (labor + parts)."""
        labor = self.labor_cost or 0
        parts = self.parts_cost or 0
        return labor + parts if (self.labor_cost or self.parts_cost) else None
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        maintenance_type = self.__dict__.get("maintenance_type", "<unloaded>")
        scheduled_at = self.__dict__.get("scheduled_at", "<unloaded>")
        return f"<MaintenanceRecord(id={id_}, type={maintenance_type}, scheduled_at={scheduled_at})>"
