"""
Purchase Indent Model

A Purchase Indent (PI) is a formal internal request to procure or transfer
items.  A Delivery Challan (DC) — the transfer shipment document — can only
be raised against an approved Purchase Indent.
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
    from app.models.transfer import Transfer


class PurchaseIndentStatus(str, enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    FULFILLED = "fulfilled"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    CANCELLED = "cancelled"


class PurchaseIndent(Base):
    """Purchase Indent — formal item-request raised before a transfer/DC."""

    __tablename__ = "purchase_indents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    indent_number: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )

    # Requesting location (who needs the items)
    requested_by_location_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=False, index=True
    )
    # Supplying location (optional — may be external procurement)
    supplying_location_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("locations.id"), nullable=True, index=True
    )

    status: Mapped[PurchaseIndentStatus] = mapped_column(
        Enum(PurchaseIndentStatus),
        default=PurchaseIndentStatus.DRAFT,
        nullable=False,
        index=True,
    )

    requested_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    approved_by_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )

    indent_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    required_by_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    requesting_location: Mapped["Location"] = relationship(
        "Location", foreign_keys=[requested_by_location_id]
    )
    supplying_location: Mapped[Optional["Location"]] = relationship(
        "Location", foreign_keys=[supplying_location_id]
    )
    requested_by: Mapped["User"] = relationship("User", foreign_keys=[requested_by_id])
    approved_by: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[approved_by_id]
    )
    items: Mapped[List["PurchaseIndentItem"]] = relationship(
        "PurchaseIndentItem",
        back_populates="indent",
        cascade="all, delete-orphan",
    )
    transfers: Mapped[List["Transfer"]] = relationship(
        "Transfer",
        back_populates="purchase_indent",
        foreign_keys="Transfer.purchase_indent_id",
    )

    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        indent_number = self.__dict__.get("indent_number", "<unloaded>")
        status = self.__dict__.get("status", "<unloaded>")
        return f"<PurchaseIndent(id={id_}, number={indent_number}, status={status})>"

    @property
    def requested_by_name(self) -> Optional[str]:
        return self.requested_by.name if self.requested_by else None

    @property
    def approved_by_name(self) -> Optional[str]:
        return self.approved_by.name if self.approved_by else None

    @property
    def requesting_location_name(self) -> Optional[str]:
        return self.requesting_location.name if self.requesting_location else None

    @property
    def supplying_location_name(self) -> Optional[str]:
        return self.supplying_location.name if self.supplying_location else None


class PurchaseIndentItem(Base):
    """Individual line item inside a Purchase Indent."""

    __tablename__ = "purchase_indent_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    indent_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("purchase_indents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("items.id"), nullable=False
    )

    quantity_requested: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_approved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_fulfilled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    indent: Mapped["PurchaseIndent"] = relationship("PurchaseIndent", back_populates="items")
    item: Mapped["Item"] = relationship("Item")

    @property
    def item_sku(self) -> Optional[str]:
        return self.item.sku if self.item else None

    @property
    def item_name(self) -> Optional[str]:
        return self.item.name if self.item else None

    @property
    def item_unit(self) -> Optional[str]:
        return self.item.unit_of_measure if self.item else None

    def __repr__(self) -> str:
        indent_id = self.__dict__.get("indent_id", "<unloaded>")
        item_id = self.__dict__.get("item_id", "<unloaded>")
        quantity_requested = self.__dict__.get("quantity_requested", "<unloaded>")
        return (
            f"<PurchaseIndentItem(indent_id={indent_id}, "
            f"item_id={item_id}, qty={quantity_requested})>"
        )
