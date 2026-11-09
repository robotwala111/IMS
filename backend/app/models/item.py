"""
Item Model

Defines inventory items and their attributes.
"""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.category import Category
    from app.models.stock import Stock, StockLot
    from app.models.asset import SerializedAsset


# Asset type classification for the UI
ASSET_TYPE_CHOICES = ("equipment", "instrument", "consumable", "accessory")


class Item(Base):
    """Inventory item master data."""
    
    __tablename__ = "items"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    id_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    sku: Mapped[Optional[str]] = mapped_column(String(50), unique=True, index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Asset type classification: equipment | instrument | consumable | accessory
    asset_type: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True, default="equipment"
    )
    
    # Category relationship
    category_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("categories.id"),
        nullable=False,
        index=True,
    )
    
    # Item specifications
    unit_of_measure: Mapped[str] = mapped_column(String(50), default="EA", nullable=False)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Valuation
    standard_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # Tracking configuration
    is_serialized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_lot_tracked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_calibration: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calibration_interval_days: Mapped[Optional[int]] = mapped_column(nullable=True)
    maintenance_interval_days: Mapped[Optional[int]] = mapped_column(nullable=True)
    has_expiry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    shelf_life_days: Mapped[Optional[int]] = mapped_column(nullable=True)
    
    # Safety and compliance
    hazardous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hazard_class: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Relationships
    category: Mapped["Category"] = relationship("Category", back_populates="items")
    attributes: Mapped[List["ItemAttribute"]] = relationship(
        "ItemAttribute",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    stocks: Mapped[List["Stock"]] = relationship(
        "Stock",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    stock_lots: Mapped[List["StockLot"]] = relationship(
        "StockLot",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    assets: Mapped[List["SerializedAsset"]] = relationship(
        "SerializedAsset",
        back_populates="item",
        cascade="all, delete-orphan",
    )
    
    @property
    def category_name(self) -> Optional[str]:
        """Get category name for serialization."""
        return self.category.name if self.category else None

    @property
    def category_type_id(self) -> Optional[str]:
        """Get category type ID for serialization."""
        return self.category.category_type_id if self.category else None

    @property
    def category_type_name(self) -> Optional[str]:
        """Get category type name for serialization."""
        return self.category.category_type_name if self.category else None

    @property
    def stock_behavior(self) -> Optional[str]:
        """Get category stock behavior for serialization."""
        return self.category.stock_behavior if self.category else None
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        sku = self.__dict__.get("sku", "<unloaded>")
        name = self.__dict__.get("name", "<unloaded>")
        return f"<Item(id={id_}, sku={sku}, name={name})>"


class ItemAttribute(Base):
    """Custom attributes for items (flexible schema)."""
    
    __tablename__ = "item_attributes"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attribute_name: Mapped[str] = mapped_column(String(100), nullable=False)
    attribute_value: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Relationship
    item: Mapped["Item"] = relationship("Item", back_populates="attributes")
    
    def __repr__(self) -> str:
        item_id = self.__dict__.get("item_id", "<unloaded>")
        attribute_name = self.__dict__.get("attribute_name", "<unloaded>")
        return f"<ItemAttribute(item_id={item_id}, name={attribute_name})>"
