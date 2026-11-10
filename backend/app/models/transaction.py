"""
Transaction Model

Defines inventory transactions (receipts, issues, returns, adjustments).
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.location import Location
    from app.models.user import User
    from app.models.stock import StockLot
    from app.models.asset import SerializedAsset


class TransactionType(str, enum.Enum):
    """Types of inventory transactions."""
    
    RECEIPT = "receipt"
    ISSUE = "issue"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    SCRAP = "scrap"
    CYCLE_COUNT = "cycle_count"


class Transaction(Base):
    """Inventory transaction record."""
    
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key", "idempotency_line", name="uq_transaction_idempotency_line"),
    )
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType),
        nullable=False,
        index=True,
    )
    
    # Item and location
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("items.id"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("locations.id"),
        nullable=False,
        index=True,
    )
    
    # Quantity (positive for in, negative for out)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Optional lot/serial tracking
    lot_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("stock_lots.id"),
        nullable=True,
    )
    asset_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("serialized_assets.id"),
        nullable=True,
    )
    
    # Valuation
    unit_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    total_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Reference information
    reference_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reference_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    idempotency_line: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    return_condition: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    
    # Reason and notes
    reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Audit
    created_by_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
    )
    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    
    # Relationships (using string references to avoid circular imports)
    item: Mapped["Item"] = relationship("Item")
    location: Mapped["Location"] = relationship("Location")
    lot: Mapped[Optional["StockLot"]] = relationship("StockLot")
    asset: Mapped[Optional["SerializedAsset"]] = relationship("SerializedAsset")
    created_by: Mapped["User"] = relationship("User")
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        transaction_type = self.__dict__.get("transaction_type", "<unloaded>")
        quantity = self.__dict__.get("quantity", "<unloaded>")
        return f"<Transaction(id={id_}, type={transaction_type}, qty={quantity})>"
