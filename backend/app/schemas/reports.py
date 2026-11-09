"""
Report Schemas

Pydantic schemas for report data.
"""

from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class ReportFormat(str, Enum):
    """Supported report export formats."""
    CSV = "csv"
    EXCEL = "xlsx"


# Inventory Report

class InventoryReportItem(BaseModel):
    """Single item in inventory report."""
    sku: Optional[str] = None
    name: str
    category_name: Optional[str] = None
    location_name: str
    location_code: str
    quantity: Decimal
    unit_of_measure: str
    unit_cost: Optional[Decimal] = None
    total_value: Optional[Decimal] = None
    reorder_point: Optional[Decimal] = None
    status: str  # "in_stock", "low_stock", "out_of_stock"


class InventoryReport(BaseModel):
    """Inventory report response."""
    generated_at: datetime
    generated_by: str
    filters: dict
    summary: dict
    items: List[InventoryReportItem]


# Transaction Report

class TransactionReportItem(BaseModel):
    """Single transaction in report."""
    reference_number: str
    transaction_type: str
    item_sku: Optional[str] = None
    item_name: str
    quantity: Decimal
    unit_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None
    location_name: str
    performed_by: str
    created_at: datetime
    notes: Optional[str] = None


class TransactionReport(BaseModel):
    """Transaction report response."""
    generated_at: datetime
    generated_by: str
    date_range: dict
    filters: dict
    summary: dict
    transactions: List[TransactionReportItem]


# Calibration Report

class CalibrationReportItem(BaseModel):
    """Single calibration record in report."""
    serial_number: str
    asset_name: str
    location_name: str
    status: str  # "current", "due_soon", "expired"
    last_calibration_date: Optional[date] = None
    due_date: date
    days_until_due: int
    performed_by: Optional[str] = None
    certificate_number: Optional[str] = None
    calibration_provider: Optional[str] = None


class CalibrationReport(BaseModel):
    """Calibration report response."""
    generated_at: datetime
    generated_by: str
    filters: dict
    summary: dict
    records: List[CalibrationReportItem]


# Stock Movement Report

class StockMovementItem(BaseModel):
    """Stock movement for a single item."""
    item_sku: Optional[str] = None
    item_name: str
    location_name: str
    opening_balance: Decimal
    receipts: Decimal
    issues: Decimal
    returns: Decimal
    adjustments: Decimal
    transfers_in: Decimal
    transfers_out: Decimal
    closing_balance: Decimal


class StockMovementReport(BaseModel):
    """Stock movement report response."""
    generated_at: datetime
    generated_by: str
    date_range: dict
    filters: dict
    summary: dict
    movements: List[StockMovementItem]


# Asset Report

class AssetReportItem(BaseModel):
    """Single asset in report."""
    serial_number: str
    name: str
    item_sku: Optional[str] = None
    location_name: str
    status: str
    assigned_to: Optional[str] = None
    purchase_date: Optional[date] = None
    purchase_price: Optional[Decimal] = None
    warranty_expiry: Optional[date] = None
    last_calibration: Optional[date] = None
    next_calibration_due: Optional[date] = None
    last_maintenance: Optional[date] = None


class AssetReport(BaseModel):
    """Asset report response."""
    generated_at: datetime
    generated_by: str
    filters: dict
    summary: dict
    assets: List[AssetReportItem]
