"""
Dashboard Endpoints

Dashboard data aggregation for inventory overview.
"""

from datetime import date, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    authorized_location_ids,
    require_location_access,
)
from app.core.logging import get_logger
from app.schemas.dashboard import (
    DashboardSummary,
    StockByLocation,
    StockByCategory,
    LowStockItem,
    RecentActivity,
    CalibrationAlert,
    TransferSummary,
    TrendData,
)
from app.schemas.stock import AllLocationsStockSummary, LocationStockSummary
from app.services.dashboard_service import DashboardService
from app.services.stock_service import StockService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/location-stock-summary", response_model=AllLocationsStockSummary)
async def get_location_stock_summary(
    current_user: CurrentUser,
    db: DB,
    location_id: Optional[str] = Query(None, description="Filter by specific location"),
) -> AllLocationsStockSummary:
    """
    Get stock summary for all locations with daily movements.
    
    Returns opening balance, received today, issued today, and closing balance.
    If location_id is provided, returns summary for just that location.
    """
    stock_service = StockService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    # If specific location requested, ensure user has access
    if location_id:
        if location_ids is not None and location_id not in location_ids:
            # User doesn't have access to this location
            from app.core.exceptions import ForbiddenError
            raise ForbiddenError(message="You don't have access to this location")
        location_ids = [location_id]
    
    return await stock_service.get_all_locations_stock_summary(location_ids=location_ids)


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    current_user: CurrentUser,
    db: DB,
) -> DashboardSummary:
    """
    Get overall dashboard summary with key metrics.
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    return await dashboard_service.get_summary(
        location_ids=location_ids,
        user=current_user,
    )


@router.get("/stock-by-location", response_model=List[StockByLocation])
async def get_stock_by_location(
    current_user: CurrentUser,
    db: DB,
) -> List[StockByLocation]:
    """
    Get stock quantity grouped by location (for pie chart).
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    return await dashboard_service.get_stock_by_location(location_ids=location_ids)


@router.get("/stock-by-category", response_model=List[StockByCategory])
async def get_stock_by_category(
    current_user: CurrentUser,
    db: DB,
    location_id: Optional[str] = Query(None),
) -> List[StockByCategory]:
    """
    Get stock quantity grouped by category (for bar chart).
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    if location_id:
        require_location_access(current_user, location_id)
    
    return await dashboard_service.get_stock_by_category(
        location_id=location_id,
        location_ids=location_ids,
    )


@router.get("/low-stock-items", response_model=List[LowStockItem])
async def get_low_stock_items(
    current_user: CurrentUser,
    db: DB,
    limit: int = Query(10, ge=1, le=100),
) -> List[LowStockItem]:
    """
    Get items that are below reorder point.
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    return await dashboard_service.get_low_stock_items(
        limit=limit,
        location_ids=location_ids,
    )


@router.get("/recent-activity", response_model=List[RecentActivity])
async def get_recent_activity(
    current_user: CurrentUser,
    db: DB,
    limit: int = Query(10, ge=1, le=200),
) -> List[RecentActivity]:
    """
    Get recent inventory activity (transactions, transfers).
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    return await dashboard_service.get_recent_activity(
        limit=limit,
        location_ids=location_ids,
    )


@router.get("/calibration-alerts", response_model=List[CalibrationAlert])
async def get_calibration_alerts(
    current_user: CurrentUser,
    db: DB,
    days: int = Query(30, ge=1, le=365),
) -> List[CalibrationAlert]:
    """
    Get assets with calibrations due soon or overdue.
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    return await dashboard_service.get_calibration_alerts(
        days=days,
        location_ids=location_ids,
    )


@router.get("/pending-transfers", response_model=TransferSummary)
async def get_pending_transfers(
    current_user: CurrentUser,
    db: DB,
) -> TransferSummary:
    """
    Get summary of pending transfers.
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    
    return await dashboard_service.get_transfer_summary(location_ids=location_ids)


@router.get("/trends/transactions", response_model=List[TrendData])
async def get_transaction_trends(
    current_user: CurrentUser,
    db: DB,
    days: int = Query(30, ge=7, le=365),
    location_id: Optional[str] = Query(None),
) -> List[TrendData]:
    """
    Get transaction trends over time (for line chart).
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    if location_id:
        require_location_access(current_user, location_id)
    
    return await dashboard_service.get_transaction_trends(
        days=days,
        location_id=location_id,
        location_ids=location_ids,
    )


@router.get("/trends/stock-value", response_model=List[TrendData])
async def get_stock_value_trends(
    current_user: CurrentUser,
    db: DB,
    days: int = Query(30, ge=7, le=365),
    location_id: Optional[str] = Query(None),
) -> List[TrendData]:
    """
    Get stock value trends over time.
    """
    dashboard_service = DashboardService(db)
    
    # Filter by user's assigned locations if not admin
    location_ids = authorized_location_ids(current_user)
    if location_id:
        require_location_access(current_user, location_id)
    
    return await dashboard_service.get_stock_value_trends(
        days=days,
        location_id=location_id,
        location_ids=location_ids,
    )
