"""
Category Model

Defines item categories for organization.
"""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.item import Item


class CategoryType(Base):
    """Configurable category type master."""

    __tablename__ = "category_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    stock_behavior: Mapped[str] = mapped_column(String(20), default="quantity", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categories: Mapped[List["Category"]] = relationship(
        "Category",
        back_populates="category_type",
    )

    def __repr__(self) -> str:
        key = self.__dict__.get("key", "<unloaded>")
        name = self.__dict__.get("name", "<unloaded>")
        return f"<CategoryType(key={key}, name={name})>"


class Category(Base):
    """Category for organizing inventory items."""
    
    __tablename__ = "categories"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # For hierarchical categories (optional)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    # Category type groups the category, while stock_behavior can override
    # whether this category is serial-based or quantity-based.
    category_type_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("category_types.id"),
        nullable=True,
        index=True,
    )
    stock_behavior: Mapped[str] = mapped_column(String(20), default="quantity", nullable=False)
    
    # Relationships
    category_type: Mapped[Optional["CategoryType"]] = relationship(
        "CategoryType",
        back_populates="categories",
    )
    items: Mapped[List["Item"]] = relationship(
        "Item",
        back_populates="category",
    )

    @property
    def category_type_name(self) -> Optional[str]:
        """Get category type name for serialization."""
        return self.category_type.name if self.category_type else None

    @property
    def category_type_key(self) -> Optional[str]:
        """Get category type key for serialization."""
        return self.category_type.key if self.category_type else None

    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        name = self.__dict__.get("name", "<unloaded>")
        return f"<Category(id={id_}, name={name})>"
