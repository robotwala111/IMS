"""
Transfer Schemas

Pydantic models for transfer operations.
"""

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.transfer import TransferStatus


class TransferItemBase(BaseModel):
    """Base transfer item fields."""
    
    item_id: str
    quantity_requested: int = Field(..., ge=1)
    lot_number: Optional[str] = Field(None, max_length=100)
    serial_numbers: Optional[List[str]] = None
    notes: Optional[str] = None


class TransferItemCreate(TransferItemBase):
    """Transfer item creation schema."""
    pass


class TransferItemResponse(BaseModel):
    """Transfer item response schema."""
    
    id: str
    transfer_id: str
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    item_is_serialized: Optional[bool] = None
    item_manufacturer: Optional[str] = None
    quantity_requested: int
    quantity_shipped: int
    quantity_received: int
    quantity_damaged: int = 0
    quantity_lost: int = 0
    lot_number: Optional[str]
    serial_numbers: Optional[List[str]]
    notes: Optional[str]
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class TransferBase(BaseModel):
    """Base transfer fields."""
    
    from_location_id: str
    to_location_id: str
    priority: str = Field("normal", pattern="^(low|normal|high|urgent)$")
    transfer_type: str = Field(
        "consumable",
        pattern="^(equipment|instrument|consumable|accessory)$",
    )
    required_by_date: Optional[datetime] = None
    return_date: Optional[datetime] = None
    return_reminder_days: Optional[int] = Field(None, ge=1, le=365, description="Days before return date to send reminder")
    request_notes: Optional[str] = None
    assigned_to_id: str = Field(..., min_length=1)
    destination_responsible_id: Optional[str] = None
    local_receiving_details: Optional[str] = Field(None, max_length=500)


class TransferCreate(TransferBase):
    """Transfer creation schema."""

    purchase_indent_id: Optional[str] = Field(
        None, description="ID of an existing approved PI — leave blank to auto-create one"
    )
    items: List[TransferItemCreate] = Field(..., min_length=1, max_length=100)

    @field_validator('required_by_date')
    @classmethod
    def required_by_date_not_in_past(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None:
            now = datetime.now(timezone.utc)
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            if v < now:
                raise ValueError('required_by_date cannot be in the past')
        return v

    @field_validator('from_location_id', 'to_location_id')
    @classmethod
    def location_ids_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Location ID must not be empty')
        return v

    @model_validator(mode='after')
    def same_location_requires_local_responsible(self) -> "TransferCreate":
        if self.from_location_id == self.to_location_id:
            if not self.destination_responsible_id:
                raise ValueError(
                    'Select a destination responsible person for same-location local transfers'
                )
            if not (self.local_receiving_details or '').strip():
                raise ValueError(
                    'Enter the receiving area/person for same-location local transfers'
                )
        return self


class TransferResponse(BaseModel):
    """Transfer response schema."""
    
    id: str
    transfer_number: str
    dc_number: Optional[str] = None
    from_location_id: str
    from_location_code: Optional[str] = None
    from_location_name: Optional[str] = None
    to_location_id: str
    to_location_code: Optional[str] = None
    to_location_name: Optional[str] = None
    status: TransferStatus
    priority: str
    transfer_type: str = "consumable"
    requested_date: datetime
    required_by_date: Optional[datetime]
    return_date: Optional[datetime] = None
    return_date_modified_reason: Optional[str] = None
    return_reminder_days: Optional[int] = None
    approved_at: Optional[datetime]
    shipped_at: Optional[datetime]
    received_at: Optional[datetime]
    requested_by_id: str
    requested_by_name: Optional[str] = None
    approved_by_id: Optional[str]
    approved_by_name: Optional[str] = None
    assigned_to_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    destination_responsible_id: Optional[str] = None
    destination_responsible_name: Optional[str] = None
    shipped_by_id: Optional[str]
    received_by_id: Optional[str]
    shipping_method: Optional[str]
    tracking_number: Optional[str]
    request_notes: Optional[str]
    approval_notes: Optional[str]
    shipping_notes: Optional[str]
    receiving_notes: Optional[str]
    rejection_reason: Optional[str]
    purchase_indent_id: Optional[str] = None
    purchase_indent_number: Optional[str] = None
    items: List[TransferItemResponse] = []
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class TransferListResponse(BaseModel):
    """Paginated transfer list response."""
    
    items: List[TransferResponse]
    total: int
    page: int
    page_size: int
    pages: int


class TransferApprovalRequest(BaseModel):
    """Transfer approval request."""
    
    approved: bool
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None


class ReturnDateUpdateRequest(BaseModel):
    """Request to modify the return date of an equipment transfer."""
    
    return_date: datetime
    reason: str = Field(..., min_length=3, max_length=500)
    return_reminder_days: Optional[int] = Field(None, ge=1, le=365, description="Days before return date to send reminder")


class TransferShipRequest(BaseModel):
    """Transfer ship request."""
    
    shipping_method: Optional[str] = Field(None, max_length=100)
    tracking_number: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None
    shipped_items: Optional[List["ShippedItemDetail"]] = None


class ShippedItemDetail(BaseModel):
    """Details of shipped item quantities."""
    
    transfer_item_id: str
    quantity_shipped: int = Field(..., ge=0)


class TransferReceiveRequest(BaseModel):
    """Transfer receive request."""
    
    notes: Optional[str] = None
    received_items: List["ReceivedItemDetail"] = Field(default_factory=list)


class ReceivedItemDetail(BaseModel):
    """Details of received item quantities."""
    
    transfer_item_id: str
    quantity_received: int = Field(..., ge=0)
    quantity_damaged: int = Field(0, ge=0)
    quantity_lost: int = Field(0, ge=0)
    lot_number: Optional[str] = None
    serial_numbers: Optional[List[str]] = None
    condition_notes: Optional[str] = None

    @model_validator(mode="after")
    def discrepancy_requires_notes(self):
        if (self.quantity_damaged or self.quantity_lost) and not (
            self.condition_notes or ""
        ).strip():
            raise ValueError("Condition notes are required for damaged or lost quantities")
        return self


class TransferSearchParams(BaseModel):
    """Transfer search/filter parameters."""
    
    from_location_id: Optional[str] = None
    to_location_id: Optional[str] = None
    status: Optional[TransferStatus] = None
    priority: Optional[str] = None
    requested_by_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    transfer_number: Optional[str] = None


class EquipmentTransferEligibilityResponse(BaseModel):
    """Equipment eligibility row for transfer compliance checks."""

    asset_id: str
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    serial_number: str
    id_number: Optional[str] = None
    location_id: str
    location_name: Optional[str] = None
    maintenance_interval_days: Optional[int] = None
    calibration_due_at: Optional[datetime] = None
    calibration_result: Optional[str] = None
    calibration_due_soon: bool = False
    requires_calibration: bool = True
    maintenance_last_completed_at: Optional[datetime] = None
    maintenance_next_due_at: Optional[datetime] = None
    maintenance_completed_this_period: bool = False
    maintenance_completed_this_month: bool = False  # kept for backwards compat
    blocked_reasons: List[str] = []
    can_transfer: bool = True


class EquipmentTransferOverviewResponse(BaseModel):
    """Transfer page overview grouped by calibration and maintenance."""

    items: List[EquipmentTransferEligibilityResponse]
    calibration_issues: List[EquipmentTransferEligibilityResponse]
    maintenance_issues: List[EquipmentTransferEligibilityResponse]


class DCDocumentResponse(BaseModel):
    """Delivery Challan document — generated when a transfer is shipped."""

    dc_number: str
    transfer_number: str
    transfer_type: str
    indent_number: Optional[str] = None
    dc_date: str
    ref_date: Optional[str] = None
    company_name: Optional[str] = None
    logo_data_url: Optional[str] = None
    issued_by: Optional[str] = None
    from_location: str
    from_location_address: Optional[str] = None
    to_location: str
    to_location_address: Optional[str] = None
    shipped_by: str
    items: List[dict]
    shipping_notes: Optional[str] = None
