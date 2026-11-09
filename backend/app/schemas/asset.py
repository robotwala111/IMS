"""
Asset Schemas

Pydantic models for serialized assets, calibration, and maintenance.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.asset import AssetStatus, CalibrationStatus, MaintenanceType


# Serialized Asset schemas

class AssetBase(BaseModel):
    """Base asset fields."""
    
    item_id: str
    serial_number: str = Field(..., min_length=1, max_length=100)
    location_id: str
    acquired_at: date
    supplier_name: Optional[str] = Field(None, max_length=255)
    invoice_number: Optional[str] = Field(None, max_length=100)
    purchase_order: Optional[str] = Field(None, max_length=100)
    cost: Optional[float] = Field(None, ge=0)
    warranty_expiry: Optional[date] = None
    asset_tag: Optional[str] = Field(None, max_length=100)
    barcode: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class AssetCreate(AssetBase):
    """Asset creation schema."""
    
    status: AssetStatus = AssetStatus.IN_SERVICE
    assigned_to_user_id: Optional[str] = None


class SerializedProductCreate(BaseModel):
    """Create an item master and serialized asset in one transaction."""

    id_number: Optional[str] = Field(None, max_length=50)
    serial_number: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    category_id: str
    location_id: str
    acquired_at: date
    manufacturer: Optional[str] = Field(None, max_length=255)
    model: Optional[str] = Field(None, max_length=255)
    supplier_name: Optional[str] = Field(None, max_length=255)
    invoice_number: Optional[str] = Field(None, max_length=100)
    purchase_order: Optional[str] = Field(None, max_length=100)
    cost: Optional[float] = Field(None, ge=0)
    calibration: Optional["CalibrationRecordCreate"] = None


class AssetUpdate(BaseModel):
    """Asset update schema (all fields optional)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    serial_number: Optional[str] = Field(None, min_length=1, max_length=100)
    location_id: Optional[str] = None
    status: Optional[AssetStatus] = None
    assigned_to_user_id: Optional[str] = None
    acquired_at: Optional[date] = None
    supplier_name: Optional[str] = Field(None, max_length=255)
    invoice_number: Optional[str] = Field(None, max_length=100)
    cost: Optional[float] = Field(None, ge=0)
    purchase_order: Optional[str] = Field(None, max_length=100)
    warranty_expiry: Optional[date] = None
    asset_tag: Optional[str] = Field(None, max_length=100)
    barcode: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class AssetResponse(BaseModel):
    """Asset response schema."""
    
    id: str
    item_id: str
    item_sku: Optional[str] = None
    item_name: Optional[str] = None
    item_id_number: Optional[str] = None
    item_category_id: Optional[str] = None
    item_manufacturer: Optional[str] = None
    item_model: Optional[str] = None
    item_asset_type: Optional[str] = None
    item_requires_calibration: bool = False
    serial_number: str
    location_id: str
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    status: AssetStatus
    calibration_status: CalibrationStatus
    assigned_to_user_id: Optional[str]
    assigned_to_name: Optional[str] = None
    acquired_at: date
    supplier_name: Optional[str]
    invoice_number: Optional[str]
    purchase_order: Optional[str]
    cost: Optional[float]
    warranty_expiry: Optional[date]
    asset_tag: Optional[str]
    barcode: Optional[str]
    notes: Optional[str]
    last_calibration_date: Optional[date] = None
    next_calibration_due: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class AssetListResponse(BaseModel):
    """Paginated asset list response."""
    
    items: List[AssetResponse]
    total: int
    page: int
    page_size: int
    pages: int


class AssetSearchParams(BaseModel):
    """Asset search/filter parameters."""
    
    item_id: Optional[str] = None
    location_id: Optional[str] = None
    status: Optional[AssetStatus] = None
    calibration_status: Optional[CalibrationStatus] = None
    assigned_to_user_id: Optional[str] = None
    serial_number: Optional[str] = None
    search: Optional[str] = None


# Calibration Record schemas

class CalibrationRecordBase(BaseModel):
    """Base calibration record fields."""

    model_config = ConfigDict(str_strip_whitespace=True)
    
    certificate_number: str = Field(..., min_length=1, max_length=100)
    performed_at: date
    due_at: date
    performed_by: str = Field(..., min_length=1, max_length=255)
    calibration_lab: Optional[str] = Field(None, max_length=255)
    calibration_procedure: Optional[str] = Field(None, max_length=255)
    result: str = Field("pass", pattern="^(pass|fail|limited)$")
    as_found_condition: Optional[str] = Field(None, max_length=50)
    as_left_condition: Optional[str] = Field(None, max_length=50)
    measurements: Optional[str] = None  # JSON string
    notes: Optional[str] = None


class CalibrationRecordCreate(CalibrationRecordBase):
    """Calibration record creation schema."""
    
    attachment_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.performed_at > date.today():
            raise ValueError("Calibration date cannot be in the future")
        if self.due_at <= self.performed_at:
            raise ValueError("Next due date must be after the calibration date")
        return self


class CalibrationRecordResponse(BaseModel):
    """Calibration record response schema."""
    
    id: str
    asset_id: str
    serial_number: Optional[str] = None
    certificate_number: str
    performed_at: date
    due_at: date
    performed_by: str
    calibration_lab: Optional[str]
    calibration_procedure: Optional[str]
    result: str
    as_found_condition: Optional[str]
    as_left_condition: Optional[str]
    measurements: Optional[str]
    attachment_id: Optional[str]
    notes: Optional[str]
    is_expired: bool
    days_until_due: int
    recorded_by_id: Optional[str]
    recorded_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class CalibrationRecordListResponse(BaseModel):
    """Paginated calibration record list response."""
    
    items: List[CalibrationRecordResponse]
    total: int
    page: int
    page_size: int
    pages: int


class CalibrationSupplierTransactionCreate(BaseModel):
    """Create a supplier calibration send/receive transaction."""

    model_config = ConfigDict(str_strip_whitespace=True)

    asset_id: str
    sent_at: date
    supplier_name: str = Field(..., min_length=1, max_length=255)
    received_at: Optional[date] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_date_range(self):
        today = date.today()
        if self.sent_at > today:
            raise ValueError("Sent date cannot be in the future")
        if self.received_at and self.received_at > today:
            raise ValueError("Receive date cannot be in the future")
        if self.received_at and self.received_at < self.sent_at:
            raise ValueError("Receive date cannot be before the sent date")
        return self


class CalibrationSupplierTransactionResponse(BaseModel):
    """Supplier calibration transaction response."""

    id: str
    asset_id: str
    serial_number: Optional[str] = None
    instrument_name: Optional[str] = None
    supplier_name: str
    sent_at: date
    received_at: Optional[date]
    notes: Optional[str]
    recorded_by_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CalibrationSupplierTransactionListResponse(BaseModel):
    """Paginated supplier calibration transaction list."""

    items: List[CalibrationSupplierTransactionResponse]
    total: int
    page: int
    page_size: int
    pages: int


# Maintenance Record schemas

class MaintenanceRecordBase(BaseModel):
    """Base maintenance record fields."""
    
    maintenance_type: MaintenanceType
    scheduled_at: datetime
    description: str = Field(..., min_length=1)
    work_order_number: Optional[str] = Field(None, max_length=100)


class MaintenanceRecordCreate(MaintenanceRecordBase):
    """Maintenance record creation schema."""

    assigned_to_id: Optional[str] = None
    # Completion fields — can be provided immediately if logging after the fact
    completed_at: Optional[datetime] = None
    work_performed: Optional[str] = None
    labor_hours: Optional[float] = Field(None, ge=0)
    labor_cost: Optional[float] = Field(None, ge=0)
    parts_cost: Optional[float] = Field(None, ge=0)
    result: Optional[str] = Field(None, max_length=50)
    notes: Optional[str] = None


class MaintenanceRecordUpdate(BaseModel):
    """Maintenance record update schema."""
    
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    work_performed: Optional[str] = None
    parts_used: Optional[str] = None  # JSON string
    labor_hours: Optional[float] = Field(None, ge=0)
    labor_cost: Optional[float] = Field(None, ge=0)
    parts_cost: Optional[float] = Field(None, ge=0)
    completed_by_id: Optional[str] = None
    result: Optional[str] = Field(None, max_length=50)
    next_maintenance_due: Optional[datetime] = None
    notes: Optional[str] = None
    attachment_id: Optional[str] = None


class MaintenanceRecordResponse(BaseModel):
    """Maintenance record response schema."""
    
    id: str
    asset_id: str
    serial_number: Optional[str] = None
    maintenance_type: MaintenanceType
    scheduled_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    work_order_number: Optional[str]
    description: str
    work_performed: Optional[str]
    parts_used: Optional[str]
    labor_hours: Optional[float]
    labor_cost: Optional[float]
    parts_cost: Optional[float]
    total_cost: Optional[float] = None
    assigned_to_id: Optional[str]
    assigned_to_name: Optional[str] = None
    completed_by_id: Optional[str]
    completed_by_name: Optional[str] = None
    attachment_id: Optional[str]
    result: Optional[str]
    next_maintenance_due: Optional[datetime]
    notes: Optional[str]
    is_completed: bool
    is_overdue: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class MaintenanceRecordListResponse(BaseModel):
    """Paginated maintenance record list response."""
    
    items: List[MaintenanceRecordResponse]
    total: int
    page: int
    page_size: int
    pages: int


class MaintenanceSearchParams(BaseModel):
    """Maintenance search/filter parameters."""
    
    asset_id: Optional[str] = None
    location_id: Optional[str] = None
    maintenance_type: Optional[MaintenanceType] = None
    completed: Optional[bool] = None
    overdue_only: bool = False
    assigned_to_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
