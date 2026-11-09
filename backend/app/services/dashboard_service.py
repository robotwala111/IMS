"""
Dashboard Service

Handles dashboard data aggregation.
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.stock import Stock
from app.models.item import Item
from app.models.location import Location
from app.models.category import Category
from app.models.transaction import Transaction
from app.models.transfer import Transfer
from app.models.asset import SerializedAsset
from app.models.calibration import CalibrationRecord
from app.models.user import User
from app.models.job import Job
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


class DashboardService:
    """Service for dashboard data aggregation."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_summary(
        self,
        location_ids: Optional[List[str]] = None,
        user = None,
    ) -> DashboardSummary:
        """Get overall dashboard summary."""
        # Total items
        items_query = select(func.count(Item.id)).where(Item.is_active == True)
        items_result = await self.db.execute(items_query)
        total_items = items_result.scalar_one()
        
        # Total categories
        categories_query = select(func.count(Category.id)).where(Category.is_active == True)
        categories_result = await self.db.execute(categories_query)
        total_categories = categories_result.scalar_one()
        
        # Total locations
        locations_query = select(func.count(Location.id)).where(Location.is_active == True)
        if location_ids is not None:
            locations_query = locations_query.where(Location.id.in_(location_ids))
        locations_result = await self.db.execute(locations_query)
        total_locations = locations_result.scalar_one()
        
        # Stock value
        stock_query = (
            select(func.sum(Stock.quantity_on_hand * func.coalesce(Item.standard_cost, 0)))
            .join(Item)
            .where(Item.is_active == True)
        )
        if location_ids is not None:
            stock_query = stock_query.where(Stock.location_id.in_(location_ids))
        stock_result = await self.db.execute(stock_query)
        total_stock_value = stock_result.scalar_one() or Decimal("0")
        
        # Low stock count
        low_stock_query = (
            select(func.count(Stock.id))
            .join(Item, Item.id == Stock.item_id)
            .where(
                and_(
                    Item.is_active == True,
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_on_hand <= Stock.reorder_point,
                )
            )
        )
        if location_ids is not None:
            low_stock_query = low_stock_query.where(Stock.location_id.in_(location_ids))
        low_stock_result = await self.db.execute(low_stock_query)
        low_stock_count = low_stock_result.scalar_one()
        
        # Out of stock count
        out_of_stock_query = (
            select(func.count(Stock.id))
            .join(Item, Item.id == Stock.item_id)
            .where(Item.is_active == True, Stock.quantity_on_hand <= 0)
        )
        if location_ids is not None:
            out_of_stock_query = out_of_stock_query.where(Stock.location_id.in_(location_ids))
        out_of_stock_result = await self.db.execute(out_of_stock_query)
        out_of_stock_count = out_of_stock_result.scalar_one()
        
        # Assets
        assets_query = select(func.count(SerializedAsset.id))
        if location_ids is not None:
            assets_query = assets_query.where(SerializedAsset.location_id.in_(location_ids))
        assets_result = await self.db.execute(assets_query)
        total_assets = assets_result.scalar_one()
        
        active_assets_query = select(func.count(SerializedAsset.id)).where(
            SerializedAsset.status.in_(["in_service"])
        )
        if location_ids is not None:
            active_assets_query = active_assets_query.where(SerializedAsset.location_id.in_(location_ids))
        active_assets_result = await self.db.execute(active_assets_query)
        active_assets = active_assets_result.scalar_one()
        
        # Calibration status
        today = date.today()
        from app.core.config import settings
        due_soon_date = today + timedelta(days=settings.CALIBRATION_ALERT_DAYS)
        
        # Count assets with calibration due soon (configured alert window)
        from sqlalchemy import literal_column
        # Subquery: latest calibration due_at per asset
        latest_cal_subq = (
            select(
                CalibrationRecord.asset_id,
                func.max(CalibrationRecord.due_at).label("latest_due"),
            )
            .group_by(CalibrationRecord.asset_id)
            .subquery()
        )
        
        cal_due_soon_query = (
            select(func.count(func.distinct(latest_cal_subq.c.asset_id)))
            .select_from(latest_cal_subq)
            .join(SerializedAsset, SerializedAsset.id == latest_cal_subq.c.asset_id)
            .where(
                and_(
                    latest_cal_subq.c.latest_due > today,
                    latest_cal_subq.c.latest_due <= due_soon_date,
                )
            )
        )
        if location_ids is not None:
            cal_due_soon_query = cal_due_soon_query.where(SerializedAsset.location_id.in_(location_ids))
        cal_due_soon_result = await self.db.execute(cal_due_soon_query)
        calibration_due_soon = cal_due_soon_result.scalar_one()
        
        cal_expired_query = (
            select(func.count(func.distinct(latest_cal_subq.c.asset_id)))
            .select_from(latest_cal_subq)
            .join(SerializedAsset, SerializedAsset.id == latest_cal_subq.c.asset_id)
            .where(latest_cal_subq.c.latest_due <= today)
        )
        if location_ids is not None:
            cal_expired_query = cal_expired_query.where(SerializedAsset.location_id.in_(location_ids))
        cal_expired_result = await self.db.execute(cal_expired_query)
        calibration_expired = cal_expired_result.scalar_one()
        
        # Transaction metrics (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        receipts_query = (
            select(
                func.count(Transaction.id),
                func.coalesce(func.sum(Transaction.total_cost), 0),
            )
            .where(
                and_(
                    Transaction.transaction_type == "receipt",
                    Transaction.created_at >= thirty_days_ago,
                )
            )
        )
        if location_ids is not None:
            receipts_query = receipts_query.where(Transaction.location_id.in_(location_ids))
        receipts_result = await self.db.execute(receipts_query)
        receipts_row = receipts_result.one()
        receipts_count = receipts_row[0]
        receipts_value = Decimal(str(receipts_row[1] or 0))
        
        issues_query = (
            select(
                func.count(Transaction.id),
                func.coalesce(func.sum(Transaction.total_cost), 0),
            )
            .where(
                and_(
                    Transaction.transaction_type == "issue",
                    Transaction.created_at >= thirty_days_ago,
                )
            )
        )
        if location_ids is not None:
            issues_query = issues_query.where(Transaction.location_id.in_(location_ids))
        issues_result = await self.db.execute(issues_query)
        issues_row = issues_result.one()
        issues_count = issues_row[0]
        issues_value = Decimal(str(issues_row[1] or 0))
        
        # Transfer metrics
        pending_transfers_query = select(func.count(Transfer.id)).where(
            Transfer.status.in_(["requested", "approved", "in_transit"])
        )
        if location_ids is not None:
            pending_transfers_query = pending_transfers_query.where(
                or_(
                    Transfer.from_location_id.in_(location_ids),
                    Transfer.to_location_id.in_(location_ids),
                )
            )
        pending_transfers_result = await self.db.execute(pending_transfers_query)
        pending_transfers = pending_transfers_result.scalar_one()
        
        completed_transfers_query = (
            select(func.count(Transfer.id))
            .where(
                and_(
                    Transfer.status == "received",
                    Transfer.received_at >= thirty_days_ago,
                )
            )
        )
        if location_ids is not None:
            completed_transfers_query = completed_transfers_query.where(
                or_(
                    Transfer.from_location_id.in_(location_ids),
                    Transfer.to_location_id.in_(location_ids),
                )
            )
        completed_transfers_result = await self.db.execute(completed_transfers_query)
        completed_transfers_30d = completed_transfers_result.scalar_one()
        
        # Total jobs (from jobs table)
        jobs_query = select(func.count(Job.id))
        if location_ids is not None:
            jobs_query = jobs_query.where(Job.location_id.in_(location_ids))
        jobs_result = await self.db.execute(jobs_query)
        total_jobs = jobs_result.scalar_one()
        
        return DashboardSummary(
            total_items=total_items,
            total_categories=total_categories,
            total_locations=total_locations,
            total_stock_value=total_stock_value,
            low_stock_count=low_stock_count,
            out_of_stock_count=out_of_stock_count,
            total_assets=total_assets,
            active_assets=active_assets,
            calibration_due_soon=calibration_due_soon,
            calibration_expired=calibration_expired,
            receipts_count=receipts_count,
            receipts_value=receipts_value,
            issues_count=issues_count,
            issues_value=issues_value,
            pending_transfers=pending_transfers,
            completed_transfers_30d=completed_transfers_30d,
            user_location_count=(
                len(location_ids) if location_ids is not None else total_locations
            ),
            total_jobs=total_jobs,
        )
    
    async def get_stock_by_location(
        self,
        location_ids: Optional[List[str]] = None,
    ) -> List[StockByLocation]:
        """Get stock distribution by location."""
        query = (
            select(
                Location.id,
                Location.name,
                Location.code,
                func.coalesce(func.sum(Stock.quantity_on_hand), 0).label("total_quantity"),
                func.coalesce(func.sum(Stock.quantity_on_hand * func.coalesce(Item.standard_cost, 0)), 0).label("total_value"),
                func.count(func.distinct(Stock.item_id)).label("item_count"),
            )
            .select_from(Location)
            .outerjoin(Stock, Stock.location_id == Location.id)
            .outerjoin(Item, Item.id == Stock.item_id)
            .where(Location.is_active == True)
            .group_by(Location.id, Location.name, Location.code)
        )
        
        if location_ids is not None:
            query = query.where(Location.id.in_(location_ids))
        
        result = await self.db.execute(query)
        
        return [
            StockByLocation(
                location_id=row.id,
                location_name=row.name,
                location_code=row.code,
                total_quantity=Decimal(str(row.total_quantity)),
                total_value=Decimal(str(row.total_value)),
                item_count=row.item_count,
            )
            for row in result.all()
        ]
    
    async def get_stock_by_category(
        self,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> List[StockByCategory]:
        """Get stock distribution by category."""
        query = (
            select(
                Category.id,
                Category.name,
                func.coalesce(func.sum(Stock.quantity_on_hand), 0).label("total_quantity"),
                func.coalesce(func.sum(Stock.quantity_on_hand * func.coalesce(Item.standard_cost, 0)), 0).label("total_value"),
                func.count(func.distinct(Item.id)).label("item_count"),
            )
            .select_from(Category)
            .outerjoin(Item, Item.category_id == Category.id)
            .outerjoin(Stock, Stock.item_id == Item.id)
            .where(Category.is_active == True)
            .group_by(Category.id, Category.name)
        )
        
        if location_id:
            query = query.where(Stock.location_id == location_id)
        elif location_ids is not None:
            query = query.where(Stock.location_id.in_(location_ids))
        
        result = await self.db.execute(query)
        
        return [
            StockByCategory(
                category_id=row.id,
                category_name=row.name,
                total_quantity=Decimal(str(row.total_quantity)),
                total_value=Decimal(str(row.total_value)),
                item_count=row.item_count,
            )
            for row in result.all()
        ]
    
    async def get_low_stock_items(
        self,
        limit: int = 10,
        location_ids: Optional[List[str]] = None,
    ) -> List[LowStockItem]:
        """Get items below reorder point."""
        query = (
            select(
                Item.id,
                Item.sku,
                Item.name,
                Item.unit_of_measure,
                Stock.reorder_point,
                Location.id.label("location_id"),
                Location.name.label("location_name"),
                Category.name.label("category_name"),
                Stock.quantity_on_hand,
            )
            .join(Stock, Stock.item_id == Item.id)
            .join(Location, Location.id == Stock.location_id)
            .outerjoin(Category, Category.id == Item.category_id)
            .where(
                and_(
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_on_hand <= Stock.reorder_point,
                    Stock.reorder_point > 0,
                )
            )
            .order_by((Stock.reorder_point - Stock.quantity_on_hand).desc())
            .limit(limit)
        )
        
        if location_ids is not None:
            query = query.where(Stock.location_id.in_(location_ids))
        
        result = await self.db.execute(query)
        
        return [
            LowStockItem(
                item_id=row.id,
                sku=row.sku,
                name=row.name,
                location_id=row.location_id,
                location_name=row.location_name,
                category_name=row.category_name,
                current_quantity=Decimal(str(row.quantity_on_hand)),
                reorder_point=Decimal(str(row.reorder_point)),
                shortage=Decimal(str(row.reorder_point - row.quantity_on_hand)),
                unit_of_measure=row.unit_of_measure,
            )
            for row in result.all()
        ]
    
    async def get_recent_activity(
        self,
        limit: int = 10,
        location_ids: Optional[List[str]] = None,
    ) -> List[RecentActivity]:
        """Get recent transactions and transfers."""
        # Get recent transactions
        transactions_query = (
            select(
                Transaction.id,
                Transaction.reference_number,
                Transaction.transaction_type,
                Transaction.quantity,
                Transaction.created_at,
                Item.name.label("item_name"),
                Location.name.label("location_name"),
                User.name.label("user_name"),
            )
            .join(Item, Item.id == Transaction.item_id)
            .join(Location, Location.id == Transaction.location_id)
            .join(User, User.id == Transaction.created_by_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        
        if location_ids is not None:
            transactions_query = transactions_query.where(Transaction.location_id.in_(location_ids))
        
        transactions_result = await self.db.execute(transactions_query)
        
        activities = []
        for row in transactions_result.all():
            activities.append(
                RecentActivity(
                    id=row.id,
                    activity_type="transaction",
                    action=row.transaction_type.value if row.transaction_type else "unknown",
                    item_name=row.item_name,
                    quantity=Decimal(str(row.quantity)) if row.quantity else Decimal("0"),
                    location_name=row.location_name,
                    performed_by=row.user_name or "Unknown",
                    created_at=row.created_at,
                    reference_number=row.reference_number,
                )
            )
        
        # Sort by created_at and limit
        activities.sort(key=lambda x: x.created_at, reverse=True)
        return activities[:limit]
    
    async def get_calibration_alerts(
        self,
        days: int = 30,
        location_ids: Optional[List[str]] = None,
    ) -> List[CalibrationAlert]:
        """Get calibration alerts - assets with calibration due soon or expired."""
        today = date.today()
        due_soon_date = today + timedelta(days=days)
        
        # Subquery: latest calibration per asset
        latest_cal_subq = (
            select(
                CalibrationRecord.asset_id,
                func.max(CalibrationRecord.due_at).label("latest_due"),
                func.max(CalibrationRecord.performed_at).label("last_performed"),
            )
            .group_by(CalibrationRecord.asset_id)
            .subquery()
        )
        
        query = (
            select(
                SerializedAsset.id,
                SerializedAsset.serial_number,
                Item.name.label("asset_name"),
                Location.name.label("location_name"),
                latest_cal_subq.c.last_performed,
                latest_cal_subq.c.latest_due,
            )
            .select_from(latest_cal_subq)
            .join(SerializedAsset, SerializedAsset.id == latest_cal_subq.c.asset_id)
            .join(Item, Item.id == SerializedAsset.item_id)
            .join(Location, Location.id == SerializedAsset.location_id)
            .where(latest_cal_subq.c.latest_due <= due_soon_date)
            .order_by(latest_cal_subq.c.latest_due.asc())
        )
        
        if location_ids is not None:
            query = query.where(SerializedAsset.location_id.in_(location_ids))
        
        result = await self.db.execute(query)
        
        alerts = []
        for row in result.all():
            days_until = (row.latest_due - today).days
            status = "expired" if days_until <= 0 else "due_soon"
            alerts.append(
                CalibrationAlert(
                    asset_id=row.id,
                    serial_number=row.serial_number,
                    asset_name=row.asset_name,
                    location_name=row.location_name,
                    last_calibration=row.last_performed,
                    due_date=row.latest_due,
                    days_until_due=days_until,
                    status=status,
                )
            )
        
        return alerts
    
    async def get_transfer_summary(
        self,
        location_ids: Optional[List[str]] = None,
    ) -> TransferSummary:
        """Get summary of pending transfers."""
        base_filter = True
        if location_ids is not None:
            base_filter = or_(
                Transfer.from_location_id.in_(location_ids),
                Transfer.to_location_id.in_(location_ids),
            )
        
        # Pending count
        pending_result = await self.db.execute(
            select(func.count(Transfer.id)).where(
                and_(base_filter, Transfer.status == "requested")
            )
        )
        pending_count = pending_result.scalar_one()
        
        # In transit count
        in_transit_result = await self.db.execute(
            select(func.count(Transfer.id)).where(
                and_(base_filter, Transfer.status == "in_transit")
            )
        )
        in_transit_count = in_transit_result.scalar_one()
        
        # Pending approval count
        pending_approval_result = await self.db.execute(
            select(func.count(Transfer.id)).where(
                and_(base_filter, Transfer.status == "requested")
            )
        )
        pending_approval_count = pending_approval_result.scalar_one()
        
        return TransferSummary(
            pending_count=pending_count,
            in_transit_count=in_transit_count,
            pending_approval_count=pending_approval_count,
            total_items_in_transit=0,  # Would need to sum transfer items
        )
    
    async def get_transaction_trends(
        self,
        days: int = 30,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> List[TrendData]:
        """Get transaction trends over time."""
        start_date = date.today() - timedelta(days=days)
        
        # This is a simplified implementation
        return []
    
    async def get_stock_value_trends(
        self,
        days: int = 30,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> List[TrendData]:
        """Get stock value trends over time."""
        # This would require historical stock value tracking
        return []
