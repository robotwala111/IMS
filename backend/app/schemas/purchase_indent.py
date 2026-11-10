"""
Purchase Indent Schemas

Pydantic models for Purchase Indent (PI) operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.purchase_indent import PurchaseIndentStatus


# ---------------------------------------------------------------------------
# Item line schemas
# ---------------------------------------------------------------------------

class PurchaseIndentItemBase(BaseModel):
    item_id: str
    quantity_requested: int = Field(..., ge=1)
    notes: Optional[str] = None


class PurchaseIndentItemCreate(PurchaseIndentItemBase):
    pass


class PurchaseIndentItemResponse(BaseModel):
    id: str
    indent_id: str
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    item_unit: Optional[str] = None
    quantity_requested: int
    quantity_approved: int
    quantity_fulfilled: int
    notes: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Indent schemas
# ---------------------------------------------------------------------------

class PurchaseIndentCreate(BaseModel):
    requested_by_location_id: str
    supplying_location_id: Optional[str] = None
    required_by_date: Optional[datetime] = None
    purpose: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = None
    items: List[PurchaseIndentItemCreate] = Field(..., min_length=1)


class PurchaseIndentResponse(BaseModel):
    id: str
    indent_number: str
    requested_by_location_id: str
    requesting_location_name: Optional[str] = None
    supplying_location_id: Optional[str] = None
    supplying_location_name: Optional[str] = None
    status: PurchaseIndentStatus
    requested_by_id: str
    requested_by_name: Optional[str] = None
    approved_by_id: Optional[str] = None
    approved_by_name: Optional[str] = None
    indent_date: datetime
    required_by_date: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    purpose: Optional[str] = None
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    items: List[PurchaseIndentItemResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PurchaseIndentListResponse(BaseModel):
    items: List[PurchaseIndentResponse]
    total: int
    page: int
    page_size: int
    pages: int


class PurchaseIndentApprovalRequest(BaseModel):
    approved: bool
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None
    # Optionally override approved quantities per line
    approved_items: Optional[List["ApprovedItemDetail"]] = None


class ApprovedItemDetail(BaseModel):
    indent_item_id: str
    quantity_approved: int = Field(..., ge=0)


class PurchaseIndentDocumentResponse(BaseModel):
    """Structured data returned by the PI print endpoint."""

    indent_number: str
    indent_date: str
    printed_by: Optional[str] = None
    printed_date: Optional[str] = None
    company_name: Optional[str] = None
    app_name: Optional[str] = None
    logo_data_url: Optional[str] = None
    required_by_date: Optional[str] = None
    requesting_location: str
    supplying_location: Optional[str] = None
    requested_by: str
    approved_by: Optional[str] = None
    status: str
    purpose: Optional[str] = None
    notes: Optional[str] = None
    items: List[dict]
    transfers: List[dict] = []
