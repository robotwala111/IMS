"""
Asset Models

Defines serialized assets, calibration records, and maintenance tracking.
"""

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.location import Location
    from app.models.user import User
    from app.models.attachment import Attachment


class AssetStatus(str, enum.Enum):
    """Status of a serialized asset."""
    
    IN_SERVICE = "in_service"
    UNDER_MAINTENANCE = "under_maintenance"
    UNDER_CALIBRATION = "under_calibration"
    OUT_OF_SERVICE = "out_of_service"
    RETIRED = "retired"
    LOST = "lost"
    TRANSFERRED = "transferred"


class CalibrationStatus(str, enum.Enum):
    """Calibration status of an asset."""
    
    VALID = "valid"
    DUE_SOON = "due_soon"
    EXPIRED = "expired"
    NOT_REQUIRED = "not_required"


class MaintenanceType(str, enum.Enum):
    """Type of maintenance activity."""
    
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    INSPECTION = "inspection"
    REPAIR = "repair"


class SerializedAsset(Base):
    """Serialized/tracked asset with unique serial number."""
    
    __tablename__ = "serialized_assets"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("items.id"),
        nullable=False,
        index=True,
    )
    serial_number: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )
    
    # Location
    location_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )
    
    # Status
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus),
        default=AssetStatus.IN_SERVICE,
        nullable=False,
        index=True,
    )
    
    # Assignment
    assigned_to_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
    )
    
    # Acquisition
    acquired_at: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    purchase_order: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    warranty_expiry: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    # Additional identification
    asset_tag: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    barcode: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="assets")
    location: Mapped["Location"] = relationship("Location", back_populates="assets")
    assigned_to: Mapped[Optional["User"]] = relationship("User")
    calibration_records: Mapped[List["CalibrationRecord"]] = relationship(
        "CalibrationRecord",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by=(
            "desc(CalibrationRecord.performed_at), "
            "desc(CalibrationRecord.created_at), "
            "desc(CalibrationRecord.id)"
        ),
    )
    maintenance_records: Mapped[List["MaintenanceRecord"]] = relationship(
        "MaintenanceRecord",
        back_populates="asset",
        cascade="all, delete-orphan",
        order_by="desc(MaintenanceRecord.scheduled_at)",
    )
    
    # --- Computed properties for API serialization ---

    @property
    def item_sku(self) -> Optional[str]:
        return self.item.sku if self.item else None

    @property
    def item_name(self) -> Optional[str]:
        return self.item.name if self.item else None

    @property
    def item_id_number(self) -> Optional[str]:
        return self.item.id_number if self.item else None

    @property
    def item_category_id(self) -> Optional[str]:
        return self.item.category_id if self.item else None

    @property
    def item_manufacturer(self) -> Optional[str]:
        return self.item.manufacturer if self.item else None

    @property
    def item_model(self) -> Optional[str]:
        return self.item.model if self.item else None

    @property
    def item_asset_type(self) -> Optional[str]:
        return self.item.asset_type if self.item else None

    @property
    def item_requires_calibration(self) -> bool:
        return self.item.requires_calibration if self.item else False

    @property
    def location_code(self) -> Optional[str]:
        return self.location.code if self.location else None

    @property
    def location_name(self) -> Optional[str]:
        return self.location.name if self.location else None

    @property
    def assigned_to_name(self) -> Optional[str]:
        return self.assigned_to.name if self.assigned_to else None

    @property
    def latest_calibration(self) -> Optional["CalibrationRecord"]:
        """Get the most recent calibration record."""
        if self.calibration_records:
            return self.calibration_records[0]
        return None

    @property
    def last_calibration_date(self) -> Optional[date]:
        latest = self.latest_calibration
        return latest.performed_at if latest else None

    @property
    def next_calibration_due(self) -> Optional[date]:
        latest = self.latest_calibration
        return latest.due_at if latest else None

    @property
    def calibration_status(self) -> CalibrationStatus:
        """Determine current calibration status."""
        from app.core.config import settings
        
        if not self.item.requires_calibration:
            return CalibrationStatus.NOT_REQUIRED
        
        latest = self.latest_calibration
        if not latest or not latest.due_at:
            return CalibrationStatus.EXPIRED
        
        days_until_due = (latest.due_at - date.today()).days
        
        if days_until_due < 0:
            return CalibrationStatus.EXPIRED
        elif days_until_due <= settings.CALIBRATION_ALERT_DAYS:
            return CalibrationStatus.DUE_SOON
        else:
            return CalibrationStatus.VALID
    
    def __repr__(self) -> str:
        serial_number = self.__dict__.get("serial_number", "<unloaded>")
        status = self.__dict__.get("status", "<unloaded>")
        return f"<SerializedAsset(serial={serial_number}, status={status})>"
