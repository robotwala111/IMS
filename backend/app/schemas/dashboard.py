"""
Dashboard Schemas

Pydantic schemas for dashboard data.
"""

from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal

from pydantic import BaseModel


class StockByLocation(BaseModel):
    """Stock distribution by location (for pie chart)."""
    location_id: str
    location_name: str
    location_code: str
    total_quantity: Decimal
    total_value: Decimal
    item_count: int


class StockByCategory(BaseModel):
    """Stock distribution by category (for bar chart)."""
    category_id: str
    category_name: str
    total_quantity: Decimal
    total_value: Decimal
    item_count: int


class LowStockItem(BaseModel):
    """Item below reorder point."""
    item_id: str
    sku: Optional[str] = None
    name: str
    location_id: str
    location_name: str
    category_name: Optional[str] = None
    current_quantity: Decimal
    reorder_point: Decimal
    shortage: Decimal
    unit_of_measure: str


class RecentActivity(BaseModel):
    """Recent transaction or transfer activity."""
    id: str
    activity_type: str  # "transaction" or "transfer"
    action: str  # "receipt", "issue", "transfer", etc.
    item_name: Optional[str] = None
    quantity: Optional[Decimal] = None
    location_name: str
    performed_by: str
    created_at: datetime
    reference_number: Optional[str] = None


class CalibrationAlert(BaseModel):
    """Asset calibration alert."""
    asset_id: str
    serial_number: str
    asset_name: str
    location_name: str
    last_calibration: Optional[date] = None
    due_date: date
    days_until_due: int
    status: str  # "due_soon", "expired"


class TransferSummary(BaseModel):
    """Summary of pending transfers."""
    pending_count: int
    in_transit_count: int
    pending_approval_count: int
    total_items_in_transit: int


class TrendData(BaseModel):
    """Time series trend data point."""
    date: date
    value: Decimal
    label: Optional[str] = None


class DashboardSummary(BaseModel):
    """Overall dashboard summary."""
    # Inventory overview
    total_items: int
    total_categories: int
    total_locations: int
    total_stock_value: Decimal
    
    # Stock status
    low_stock_count: int
    out_of_stock_count: int
    
    # Asset status
    total_assets: int
    active_assets: int
    calibration_due_soon: int
    calibration_expired: int
    
    # Transaction metrics (last 30 days)
    receipts_count: int
    receipts_value: Decimal
    issues_count: int
    issues_value: Decimal
    
    # Transfer metrics
    pending_transfers: int
    completed_transfers_30d: int
    
    # User info
    user_location_count: int
    
    # Jobs (transactions)
    total_jobs: int = 0
