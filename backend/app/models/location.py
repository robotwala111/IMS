"""
Location Model

Defines physical inventory locations.
"""

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.stock import Stock, StockLot
    from app.models.asset import SerializedAsset


class Location(Base):
    """Physical location where inventory is stored."""
    
    __tablename__ = "locations"
    
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    
    # Relationships
    assigned_users: Mapped[List["User"]] = relationship(
        "User",
        secondary="user_locations",
        back_populates="assigned_locations",
    )
    stocks: Mapped[List["Stock"]] = relationship(
        "Stock",
        back_populates="location",
        cascade="all, delete-orphan",
    )
    stock_lots: Mapped[List["StockLot"]] = relationship(
        "StockLot",
        back_populates="location",
        cascade="all, delete-orphan",
    )
    assets: Mapped[List["SerializedAsset"]] = relationship(
        "SerializedAsset",
        back_populates="location",
    )
    
    def __repr__(self) -> str:
        id_ = self.__dict__.get("id", "<unloaded>")
        code = self.__dict__.get("code", "<unloaded>")
        name = self.__dict__.get("name", "<unloaded>")
        return f"<Location(id={id_}, code={code}, name={name})>"
