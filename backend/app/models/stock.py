"""
Stock Model

Defines stock levels and lot tracking for inventory.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.item import Item
    from app.models.location import Location


class Stock(Base):
    """Stock level tracking per item per location."""
    
    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint("item_id", "location_id", name="uq_stock_item_location"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_stock_on_hand_nonnegative"),
        CheckConstraint("quantity_reserved >= 0", name="ck_stock_reserved_nonnegative"),
        CheckConstraint("quantity_reserved <= quantity_on_hand", name="ck_stock_reserved_not_above_on_hand"),
        CheckConstraint("quantity_on_order >= 0", name="ck_stock_on_order_nonnegative"),
        CheckConstraint("min_level >= 0", name="ck_stock_min_level_nonnegative"),
        CheckConstraint("reorder_point >= 0", name="ck_stock_reorder_point_nonnegative"),
        CheckConstraint("reorder_quantity IS NULL OR reorder_quantity >= 0", name="ck_stock_reorder_quantity_nonnegative"),
        CheckConstraint("max_level IS NULL OR max_level >= 0", name="ck_stock_max_level_nonnegative"),
    )
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Quantities
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_on_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Thresholds
    min_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reorder_point: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Bin/location within warehouse
    bin_location: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="stocks")
    location: Mapped["Location"] = relationship("Location", back_populates="stocks")
    
    @property
    def available_quantity(self) -> int:
        """Quantity available for issue (not reserved)."""
        return max(0, self.quantity_on_hand - self.quantity_reserved)
    
    @property
    def is_low_stock(self) -> bool:
        """Check if stock is below reorder point."""
        return self.quantity_on_hand <= self.reorder_point
    
    @property
    def item_sku(self) -> Optional[str]:
        """Get item SKU for serialization."""
        return self.item.sku if self.item else None
    
    @property
    def item_name(self) -> Optional[str]:
        """Get item name for serialization."""
        return self.item.name if self.item else None
    
    @property
    def location_code(self) -> Optional[str]:
        """Get location code for serialization."""
        return self.location.code if self.location else None
    
    @property
    def location_name(self) -> Optional[str]:
        """Get location name for serialization."""
        return self.location.name if self.location else None
    
    def __repr__(self) -> str:
        item_id = self.__dict__.get("item_id", "<unloaded>")
        location_id = self.__dict__.get("location_id", "<unloaded>")
        quantity_on_hand = self.__dict__.get("quantity_on_hand", "<unloaded>")
        return f"<Stock(item_id={item_id}, location_id={location_id}, qty={quantity_on_hand})>"


class StockLot(Base):
    """Lot/batch tracking for items with expiry or lot control."""
    
    __tablename__ = "stock_lots"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    # Lot identification
    lot_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    
    # Quantity
    quantity_on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    
    # Dates
    manufacture_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    
    # Supplier and cost
    supplier: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    supplier_lot: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cost_per_unit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Quality
    certificate_of_analysis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Relationships
    item: Mapped["Item"] = relationship("Item", back_populates="stock_lots")
    location: Mapped["Location"] = relationship("Location", back_populates="stock_lots")
    
    @property
    def is_expired(self) -> bool:
        """Check if lot has expired."""
        if self.expiry_date:
            return self.expiry_date < date.today()
        return False
    
    @property
    def days_until_expiry(self) -> Optional[int]:
        """Days remaining until expiry."""
        if self.expiry_date:
            return (self.expiry_date - date.today()).days
        return None
    
    @property
    def available_quantity(self) -> int:
        """Quantity available for issue (not reserved)."""
        return max(0, self.quantity_on_hand - self.quantity_reserved)
    
    def __repr__(self) -> str:
        lot_number = self.__dict__.get("lot_number", "<unloaded>")
        item_id = self.__dict__.get("item_id", "<unloaded>")
        quantity_on_hand = self.__dict__.get("quantity_on_hand", "<unloaded>")
        return f"<StockLot(lot={lot_number}, item_id={item_id}, qty={quantity_on_hand})>"
