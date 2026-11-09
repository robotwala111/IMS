"""
Transfer Model

Defines inter-location transfer workflows with approval.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.location import Location
    from app.models.user import User
    from app.models.item import Item
    from app.models.purchase_indent import PurchaseIndent


class TransferStatus(str, enum.Enum):
    """Status of a transfer request."""
    
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"
    PARTIALLY_RECEIVED = "partially_received"


class Transfer(Base):
    """Inter-location transfer request."""
    
    __tablename__ = "transfers"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    dc_number: Mapped[Optional[str]] = mapped_column(
        String(50), unique=True, index=True, nullable=True
    )
    
    # Locations
    from_location_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )
    to_location_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )
    
    # Status and workflow
    status: Mapped[TransferStatus] = mapped_column(
        Enum(TransferStatus),
        default=TransferStatus.REQUESTED,
        nullable=False,
        index=True,
    )
    
    # Priority and dates
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    requested_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    required_by_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    return_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    return_date_modified_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    return_reminder_days: Mapped[Optional[int]] = mapped_column(nullable=True, default=3)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Personnel
    requested_by_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
    )
    approved_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
    )
    shipped_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
    )
    received_by_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
    )
    
    # Assigned handler at source location — person responsible for fulfilling
    assigned_to_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    destination_responsible_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    
    # Shipping details
    shipping_method: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Transfer type
    transfer_type: Mapped[str] = mapped_column(String(20), default="consumable", nullable=False)

    # Purchase Indent linkage — every transfer must reference an approved PI
    purchase_indent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("purchase_indents.id"),
        nullable=True,
        index=True,
    )
    purchase_indent_number: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    request_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    shipping_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    receiving_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    from_location: Mapped["Location"] = relationship(
        "Location",
        foreign_keys=[from_location_id],
    )
    to_location: Mapped["Location"] = relationship(
        "Location",
        foreign_keys=[to_location_id],
    )
    requested_by: Mapped["User"] = relationship(
        "User",
        foreign_keys=[requested_by_id],
    )
    approved_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[approved_by_id],
    )
    shipped_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[shipped_by_id],
    )
    received_by: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[received_by_id],
    )
    assigned_to: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[assigned_to_id],
    )
    destination_responsible: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[destination_responsible_id],
    )
    items: Mapped[List["TransferItem"]] = relationship(
        "TransferItem",
        back_populates="transfer",
        cascade="all, delete-orphan",
    )
    purchase_indent: Mapped[Optional["PurchaseIndent"]] = relationship(
        "PurchaseIndent",
        back_populates="transfers",
        foreign_keys=[purchase_indent_id],
    )
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        transfer_number = self.__dict__.get("transfer_number", "<unloaded>")
        status = self.__dict__.get("status", "<unloaded>")
        return f"<Transfer(id={id_}, number={transfer_number}, status={status})>"

    @property
    def from_location_name(self) -> Optional[str]:
        return self.from_location.name if self.from_location else None

    @property
    def from_location_code(self) -> Optional[str]:
        return self.from_location.code if self.from_location else None

    @property
    def to_location_name(self) -> Optional[str]:
        return self.to_location.name if self.to_location else None

    @property
    def to_location_code(self) -> Optional[str]:
        return self.to_location.code if self.to_location else None

    @property
    def requested_by_name(self) -> Optional[str]:
        return self.requested_by.name if self.requested_by else None

    @property
    def approved_by_name(self) -> Optional[str]:
        return self.approved_by.name if self.approved_by else None

    @property
    def assigned_to_name(self) -> Optional[str]:
        return self.assigned_to.name if self.assigned_to else None

    @property
    def destination_responsible_name(self) -> Optional[str]:
        return self.destination_responsible.name if self.destination_responsible else None


class TransferItem(Base):
    """Individual item line in a transfer."""
    
    __tablename__ = "transfer_items"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transfer_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("transfers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("items.id"),
        nullable=False,
    )
    
    # Quantities
    quantity_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_damaged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_lost: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Lot/serial tracking
    lot_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    serial_numbers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    
    # Notes
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    transfer: Mapped["Transfer"] = relationship("Transfer", back_populates="items")
    item: Mapped["Item"] = relationship("Item")

    @property
    def item_sku(self) -> Optional[str]:
        """Get item SKU for serialization."""
        return self.item.sku if self.item else None

    @property
    def item_name(self) -> Optional[str]:
        """Get item name for serialization."""
        return self.item.name if self.item else None

    @property
    def item_is_serialized(self) -> Optional[bool]:
        """Get item serialization flag for transfer type classification."""
        return self.item.is_serialized if self.item else None

    @property
    def item_manufacturer(self) -> Optional[str]:
        """Get item manufacturer for serialization."""
        return self.item.manufacturer if self.item else None
    
    def __repr__(self) -> str:
        transfer_id = self.__dict__.get("transfer_id", "<unloaded>")
        item_id = self.__dict__.get("item_id", "<unloaded>")
        quantity_requested = self.__dict__.get("quantity_requested", "<unloaded>")
        return f"<TransferItem(transfer_id={transfer_id}, item_id={item_id}, qty={quantity_requested})>"
