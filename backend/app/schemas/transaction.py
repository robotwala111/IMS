"""
Transaction Schemas

Pydantic models for inventory transactions.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.transaction import TransactionType


class TransactionBase(BaseModel):
    """Base transaction fields."""
    
    item_id: str
    location_id: str
    quantity: int = Field(..., ge=1)
    reference_number: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class TransactionCreate(TransactionBase):
    """Transaction creation schema (internal use)."""
    
    transaction_type: TransactionType
    lot_id: Optional[str] = None
    asset_id: Optional[str] = None
    unit_cost: Optional[float] = Field(None, ge=0)
    reason: Optional[str] = Field(None, max_length=255)


class TransactionResponse(BaseModel):
    """Transaction response schema."""
    
    id: str
    transaction_type: TransactionType
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    location_id: str
    location_code: Optional[str] = None
    quantity: int
    lot_id: Optional[str]
    lot_number: Optional[str] = None
    asset_id: Optional[str]
    serial_number: Optional[str] = None
    unit_cost: Optional[float]
    total_cost: Optional[float]
    reference_type: Optional[str]
    reference_id: Optional[str]
    reference_number: Optional[str]
    return_condition: Optional[str] = None
    reason: Optional[str]
    notes: Optional[str]
    created_by_id: str
    created_by_name: Optional[str] = None
    transaction_date: datetime
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class TransactionListResponse(BaseModel):
    """Paginated transaction list response."""
    
    items: List[TransactionResponse]
    total: int
    page: int
    page_size: int
    pages: int


# Receipt (stock in)

class ReceiptLineItem(BaseModel):
    """Single line item in a receipt."""
    
    item_id: str
    quantity: int = Field(..., ge=1)
    unit_cost: Optional[float] = Field(None, ge=0)
    lot_number: Optional[str] = Field(None, max_length=100)
    expiry_date: Optional[date] = None
    serial_numbers: Optional[List[str]] = None  # For serialized items


class ReceiptRequest(BaseModel):
    """Stock receipt request."""
    
    location_id: str
    reference_number: Optional[str] = Field(None, max_length=100)
    supplier: Optional[str] = Field(None, max_length=255)
    received_date: Optional[datetime] = None
    notes: Optional[str] = None
    line_items: List[ReceiptLineItem] = Field(..., min_length=1)


# Issue (stock out)

class IssueLineItem(BaseModel):
    """Single line item in an issue."""
    
    item_id: str
    quantity: int = Field(..., ge=1)
    lot_id: Optional[str] = None  # For lot-tracked items
    serial_numbers: Optional[List[str]] = None  # For serialized items
    notes: Optional[str] = None


class IssueRequest(BaseModel):
    """Stock issue request."""
    
    location_id: str
    reference_number: Optional[str] = Field(None, max_length=100)
    issued_to: Optional[str] = Field(None, max_length=255)
    reason: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    line_items: List[IssueLineItem] = Field(..., min_length=1)
    admin_override: bool = False  # For expired calibration override


# Return

class ReturnLineItem(BaseModel):
    """Single line item in a return."""
    
    item_id: str
    original_issue_id: str
    quantity: int = Field(..., ge=1)
    lot_id: Optional[str] = None
    serial_numbers: Optional[List[str]] = None
    condition: str = Field("good", pattern="^(good|damaged|expired)$")
    notes: Optional[str] = None


class ReturnRequest(BaseModel):
    """Stock return request."""
    
    location_id: str
    reference_number: Optional[str] = Field(None, max_length=100)
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=100)
    returned_by: Optional[str] = Field(None, max_length=255)
    reason: Optional[str] = Field(None, max_length=255)
    notes: Optional[str] = None
    line_items: List[ReturnLineItem] = Field(..., min_length=1)


class TransactionSearchParams(BaseModel):
    """Transaction search/filter parameters."""
    
    item_id: Optional[str] = None
    location_id: Optional[str] = None
    transaction_type: Optional[TransactionType] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    created_by_id: Optional[str] = None
    reference_number: Optional[str] = None
