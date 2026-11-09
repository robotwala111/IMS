"""Report totals, date boundaries, and spreadsheet export regression tests."""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock
from app.models.transaction import Transaction, TransactionType
from app.models.user import User, UserRole
from app.schemas.reports import ReportFormat
from app.services.dashboard_service import DashboardService
from app.services.report_service import ReportService


@pytest_asyncio.fixture
async def report_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        category_type = CategoryType(
            id="report-type", key="consumable", name="Consumable", stock_behavior="quantity"
        )
        category = Category(
            id="report-category", name="Report Category", category_type=category_type,
            stock_behavior="quantity", is_active=True,
        )
        location = Location(id="report-location", code="RPT", name="Report Location", is_active=True)
        user = User(
            id="report-user", email="report@example.com", name="Reporter",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[location],
        )
        active_item = Item(
            id="active-report-item", sku=None, name="=Formula-looking item", category=category,
            standard_cost=2, is_active=True,
        )
        inactive_item = Item(
            id="inactive-report-item", sku="OLD", name="Inactive", category=category,
            standard_cost=100, is_active=False,
        )
        db.add_all([
            category_type, category, location, user, active_item, inactive_item,
            Stock(id="active-stock", item=active_item, location=location, quantity_on_hand=10,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=2),
            Stock(id="inactive-stock", item=inactive_item, location=location, quantity_on_hand=10,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=20),
        ])
        transactions = [
            ("opening", TransactionType.RECEIPT, 10, datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc)),
            ("start", TransactionType.ISSUE, 2, datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)),
            ("end", TransactionType.RECEIPT, 3, datetime(2026, 2, 28, 23, 59, 59, tzinfo=timezone.utc)),
            ("outside", TransactionType.RECEIPT, 5, datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)),
        ]
        for txn_id, txn_type, quantity, txn_date in transactions:
            db.add(Transaction(
                id=f"txn-{txn_id}", transaction_type=txn_type, item=active_item,
                location=location, quantity=quantity, reference_number=f"REF-{txn_id}",
                created_by_id=user.id, transaction_date=txn_date,
            ))
        await db.commit()
        yield db, location, active_item
    await engine.dispose()


@pytest.mark.asyncio
async def test_dashboard_stock_value_matches_inventory_detail(report_context):
    db, location, _ = report_context
    inventory = await ReportService(db).generate_inventory_report(location_ids=[location.id])
    dashboard = await DashboardService(db).get_summary(location_ids=[location.id])

    assert inventory.summary["total_value"] == 20.0
    assert float(dashboard.total_stock_value) == inventory.summary["total_value"]
    assert inventory.summary["total_items"] == 1
    assert dashboard.low_stock_count == 0


@pytest.mark.asyncio
async def test_transaction_report_uses_inclusive_business_date_boundaries(report_context):
    db, location, _ = report_context
    report = await ReportService(db).generate_transaction_report(
        date(2026, 2, 1), date(2026, 2, 28), location_ids=[location.id]
    )
    assert {row.reference_number for row in report.transactions} == {"REF-start", "REF-end"}


@pytest.mark.asyncio
async def test_stock_movement_reconciles_opening_and_closing(report_context):
    db, location, _ = report_context
    report = await ReportService(db).generate_stock_movement_report(
        date(2026, 2, 1), date(2026, 2, 28), location_ids=[location.id]
    )
    movement = report.movements[0]
    assert movement.opening_balance == Decimal("10")
    assert movement.issues == Decimal("2")
    assert movement.receipts == Decimal("3")
    assert movement.closing_balance == Decimal("11")
    assert report.summary == {"total_items": 1, "total_movement": 5.0}


def test_invalid_report_date_range_is_rejected():
    with pytest.raises(BadRequestError, match="End date"):
        ReportService._date_bounds(date(2026, 2, 2), date(2026, 2, 1))


def test_csv_formula_injection_is_neutralized_and_blank_sku_is_preserved():
    service = ReportService(None)
    content, _, _ = service._export_to_csv(
        ["SKU", "Name"], [[None, "=HYPERLINK(\"https://bad\")"], ["", "+cmd"]], "safe.csv"
    )
    rows = list(csv.reader(io.StringIO(content.getvalue().decode("utf-8"))))
    assert rows[1][0] == ""
    assert rows[1][1].startswith("'=")
    assert rows[2][1] == "'+cmd"

