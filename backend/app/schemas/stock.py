"""
Stock Schemas

Pydantic models for stock and lot operations.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StockBase(BaseModel):
    """Base stock fields."""
    
    item_id: str
    location_id: str
    min_level: int = Field(0, ge=0)
    max_level: Optional[int] = Field(None, ge=0)
    reorder_point: int = Field(0, ge=0)
    reorder_quantity: Optional[int] = Field(None, ge=0)
    bin_location: Optional[str] = Field(None, max_length=50)


class StockResponse(BaseModel):
    """Stock level response schema."""
    
    id: str
    is_active: bool
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    location_id: str
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    quantity_on_hand: int
    quantity_reserved: int
    quantity_on_order: int
    available_quantity: int
    min_level: int
    max_level: Optional[int]
    reorder_point: int
    reorder_quantity: Optional[int]
    bin_location: Optional[str]
    is_low_stock: bool
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class StockListResponse(BaseModel):
    """Paginated stock list response."""
    
    items: List[StockResponse]
    total: int
    page: int
    page_size: int
    pages: int


class StockAdjustmentRequest(BaseModel):
    """Stock adjustment request."""
    
    item_id: str
    location_id: str
    quantity_change: int = Field(..., ge=-100000, le=100000, description="Non-zero quantity change (positive or negative, max ±100,000)")
    reason: str = Field(..., min_length=1, max_length=255)
    notes: Optional[str] = None
    lot_id: Optional[str] = None


class StockIssueRequest(BaseModel):
    """Stock issue request - for issuing stock to a process."""
    
    item_id: str
    location_id: str
    to_location_id: Optional[str] = None
    transfer_type: str = Field("consumable", pattern="^(consumable|accessory)$")
    quantity: int = Field(..., gt=0, description="Quantity to issue (must be positive)")
    reason: str = Field(..., min_length=1, max_length=255)
    reference_number: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None
    lot_id: Optional[str] = None


class StockThresholdUpdate(BaseModel):
    """Update stock thresholds."""
    
    min_level: Optional[int] = Field(None, ge=0)
    max_level: Optional[int] = Field(None, ge=0)
    reorder_point: Optional[int] = Field(None, ge=0)
    reorder_quantity: Optional[int] = Field(None, ge=0)
    bin_location: Optional[str] = Field(None, max_length=50)


class StockLocationCorrection(BaseModel):
    """Correct the location assigned to an existing stock balance."""

    location_id: str = Field(..., min_length=1)
    reason: str = Field(
        "Location corrected from Edit Stock Item",
        min_length=1,
        max_length=255,
    )


# Stock Lot schemas

class StockLotBase(BaseModel):
    """Base stock lot fields."""
    
    item_id: str
    location_id: str
    lot_number: str = Field(..., min_length=1, max_length=100)
    quantity_on_hand: int = Field(..., ge=0)
    manufacture_date: Optional[date] = None
    expiry_date: Optional[date] = None
    supplier: Optional[str] = Field(None, max_length=255)
    supplier_lot: Optional[str] = Field(None, max_length=100)
    cost_per_unit: Optional[float] = Field(None, ge=0)
    certificate_of_analysis: Optional[str] = None


class StockLotCreate(StockLotBase):
    """Stock lot creation schema."""
    pass


class StockLotResponse(BaseModel):
    """Stock lot response schema."""
    
    id: str
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    location_id: str
    location_code: Optional[str] = None
    lot_number: str
    quantity_on_hand: int
    quantity_reserved: int
    available_quantity: int
    manufacture_date: Optional[date]
    expiry_date: Optional[date]
    received_at: datetime
    supplier: Optional[str]
    supplier_lot: Optional[str]
    cost_per_unit: Optional[float]
    is_expired: bool
    days_until_expiry: Optional[int]
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class StockLotListResponse(BaseModel):
    """Paginated stock lot list response."""
    
    items: List[StockLotResponse]
    total: int
    page: int
    page_size: int
    pages: int


class StockSearchParams(BaseModel):
    """Stock search/filter parameters."""
    
    item_id: Optional[str] = None
    location_id: Optional[str] = None
    low_stock_only: bool = False
    category_id: Optional[str] = None


class LotSearchParams(BaseModel):
    """Lot search/filter parameters."""
    
    item_id: Optional[str] = None
    location_id: Optional[str] = None
    expiring_within_days: Optional[int] = None
    expired_only: bool = False
    lot_number: Optional[str] = None


class LocationStockItem(BaseModel):
    """Stock item details for location-wise display."""
    
    stock_id: str
    item_id: str
    sku: Optional[str] = None
    name: str
    id_number: Optional[str] = None
    latest_received_date: Optional[datetime] = None
    latest_activity_date: Optional[datetime] = None
    description: Optional[str] = None
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    category_id: Optional[str] = None
    category_name: Optional[str] = None
    category_type_name: Optional[str] = None
    category_type_key: Optional[str] = None
    stock_behavior: Optional[str] = None
    is_serialized: bool = False
    unit_of_measure: str
    opening_balance: int = 0
    received_today: int = 0
    issued_today: int = 0
    adjusted_today: int = 0
    closing_balance: int = 0
    reserved: int = 0
    available: int = 0
    reorder_point: int = 0
    is_low_stock: bool = False
    batches: List[dict] = []


class LocationStockSummary(BaseModel):
    """Location-wise stock summary with daily movements."""
    
    location_id: str
    location_code: str
    location_name: str
    total_items: int = 0
    total_quantity: int = 0
    low_stock_count: int = 0
    items: List[LocationStockItem] = []


class AllLocationsStockSummary(BaseModel):
    """Summary across all locations."""
    
    total_items: int = 0
    total_quantity: int = 0
    total_received_today: int = 0
    total_issued_today: int = 0
    total_adjusted_today: int = 0
    low_stock_count: int = 0
    locations: List[LocationStockSummary] = []
