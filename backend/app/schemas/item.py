"""
Item Schemas

Pydantic models for item and item attribute operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ItemAttributeBase(BaseModel):
    """Base item attribute fields."""
    
    attribute_name: str = Field(..., min_length=1, max_length=100)
    attribute_value: str


class ItemAttributeCreate(ItemAttributeBase):
    """Item attribute creation schema."""
    pass


class ItemAttributeResponse(ItemAttributeBase):
    """Item attribute response schema."""
    
    id: str
    item_id: str
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ItemBase(BaseModel):
    """Base item fields."""
    
    id_number: Optional[str] = Field(None, max_length=50)
    sku: Optional[str] = Field(None, max_length=50)
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    category_id: str
    asset_type: Optional[str] = Field("equipment", min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    unit_of_measure: str = Field("EA", max_length=50)
    manufacturer: Optional[str] = Field(None, max_length=255)
    model: Optional[str] = Field(None, max_length=255)
    standard_cost: Optional[float] = Field(None, ge=0)
    
    # Tracking configuration
    is_serialized: bool = False
    is_lot_tracked: bool = False
    requires_calibration: bool = False
    calibration_interval_days: Optional[int] = Field(None, ge=1)
    maintenance_interval_days: Optional[int] = Field(None, ge=1)
    has_expiry: bool = False
    shelf_life_days: Optional[int] = Field(None, ge=1)
    
    # Safety
    hazardous: bool = False
    hazard_class: Optional[str] = Field(None, max_length=50)

    @field_validator("sku", mode="before")
    @classmethod
    def blank_sku_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ItemCreate(ItemBase):
    """Item creation schema."""
    
    is_active: bool = True
    attributes: List[ItemAttributeCreate] = []
    
    # Initial stock (optional - creates stock record at location)
    initial_location_id: Optional[str] = None
    initial_quantity: Optional[int] = Field(None, ge=0)
    initial_reorder_point: Optional[int] = Field(None, ge=0)


class ItemUpdate(BaseModel):
    """Item update schema (all fields optional)."""
    
    sku: Optional[str] = Field(None, max_length=50)
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    category_id: Optional[str] = None
    asset_type: Optional[str] = Field(None, min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    unit_of_measure: Optional[str] = Field(None, max_length=50)
    manufacturer: Optional[str] = Field(None, max_length=255)
    model: Optional[str] = Field(None, max_length=255)
    id_number: Optional[str] = Field(None, max_length=50)
    standard_cost: Optional[float] = Field(None, ge=0)
    is_serialized: Optional[bool] = None
    is_lot_tracked: Optional[bool] = None
    requires_calibration: Optional[bool] = None
    calibration_interval_days: Optional[int] = Field(None, ge=1)
    maintenance_interval_days: Optional[int] = Field(None, ge=1)
    has_expiry: Optional[bool] = None
    shelf_life_days: Optional[int] = Field(None, ge=1)
    hazardous: Optional[bool] = None
    hazard_class: Optional[str] = Field(None, max_length=50)
    is_active: Optional[bool] = None

    @field_validator("sku", mode="before")
    @classmethod
    def blank_sku_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class ItemResponse(BaseModel):
    """Item response schema."""
    
    id: str
    id_number: Optional[str] = None
    sku: Optional[str] = None
    name: str
    description: Optional[str]
    category_id: str
    category_name: Optional[str] = None
    category_type_id: Optional[str] = None
    category_type_name: Optional[str] = None
    stock_behavior: Optional[str] = None
    asset_type: Optional[str] = None
    unit_of_measure: str
    manufacturer: Optional[str]
    model: Optional[str]
    standard_cost: Optional[float]
    is_serialized: bool
    is_lot_tracked: bool
    requires_calibration: bool
    calibration_interval_days: Optional[int]
    maintenance_interval_days: Optional[int] = None
    has_expiry: bool
    shelf_life_days: Optional[int]
    hazardous: bool
    hazard_class: Optional[str]
    is_active: bool
    attributes: List[ItemAttributeResponse] = []
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class ItemListResponse(BaseModel):
    """Paginated item list response."""
    
    items: List[ItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ItemSummary(BaseModel):
    """Brief item info for dropdowns."""
    
    id: str
    sku: Optional[str] = None
    name: str
    is_serialized: bool
    is_lot_tracked: bool
    
    model_config = ConfigDict(from_attributes=True)


class ItemSearchParams(BaseModel):
    """Item search/filter parameters."""
    
    search: Optional[str] = None
    category_id: Optional[str] = None
    is_serialized: Optional[bool] = None
    is_lot_tracked: Optional[bool] = None
    requires_calibration: Optional[bool] = None
    hazardous: Optional[bool] = None
    is_active: Optional[bool] = None
