"""Concurrency, database invariant, and transaction rollback tests for quantity stock."""

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock, StockLot
from app.models.transaction import Transaction
from app.models.user import User, UserRole
from app.schemas.transaction import IssueLineItem, IssueRequest
from app.services.stock_service import StockService
from app.services.transaction_service import TransactionService


@pytest_asyncio.fixture
async def stock_sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield sessions
    await engine.dispose()


def test_stock_lock_query_uses_for_update():
    statement = select(Stock).where(
        Stock.item_id == "item-a", Stock.location_id == "loc-a"
    ).with_for_update()
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [
    {"quantity_on_hand": -1, "quantity_reserved": 0},
    {"quantity_on_hand": 1, "quantity_reserved": -1},
    {"quantity_on_hand": 1, "quantity_reserved": 2},
])
async def test_database_rejects_invalid_stock_quantities(stock_sessions, values):
    async with stock_sessions() as db:
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        item = Item(id="item-a", name="Item A", category=category, is_serialized=False)
        location = Location(id="loc-a", code="A", name="Location A")
        db.add_all([category, item, location])
        await db.flush()
        db.add(Stock(
            id="stock-a", item_id=item.id, location_id=location.id,
            quantity_on_order=0, min_level=0, reorder_point=0,
            **values,
        ))
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_multi_line_issue_rolls_back_when_later_line_fails(stock_sessions):
    async with stock_sessions() as db:
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        first = Item(id="item-a", name="Item A", category=category, is_serialized=False)
        second = Item(id="item-b", name="Item B", category=category, is_serialized=False)
        location = Location(id="loc-a", code="A", name="Location A")
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        db.add_all([
            category, first, second, location, user,
            Stock(id="stock-a", item=first, location=location, quantity_on_hand=5,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0),
            Stock(id="stock-b", item=second, location=location, quantity_on_hand=0,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0),
        ])
        await db.commit()

        with pytest.raises(BadRequestError, match="Insufficient stock"):
            await TransactionService(db).process_issue(
                IssueRequest(location_id=location.id, line_items=[
                    IssueLineItem(item_id=first.id, quantity=1),
                    IssueLineItem(item_id=second.id, quantity=1),
                ]),
                user_id=user.id,
            )
        await db.rollback()

        first_stock = (await db.execute(select(Stock).where(Stock.id == "stock-a"))).scalar_one()
        assert first_stock.quantity_on_hand == 5


@pytest.mark.asyncio
async def test_quantity_issue_rejects_serialized_product(stock_sessions):
    async with stock_sessions() as db:
        category = Category(id="category-a", name="Category A", stock_behavior="serialized")
        item = Item(id="item-a", name="Serialized Item", category=category, is_serialized=True)
        location = Location(id="loc-a", code="A", name="Location A")
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        db.add_all([category, item, location, user, Stock(
            id="stock-a", item=item, location=location, quantity_on_hand=1,
            quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0,
        )])
        await db.commit()

        with pytest.raises(BadRequestError, match="Serialized products"):
            await TransactionService(db).process_issue(
                IssueRequest(location_id=location.id, line_items=[
                    IssueLineItem(item_id=item.id, quantity=1)
                ]), user_id=user.id,
            )


@pytest.mark.asyncio
async def test_lot_issue_uses_fefo_and_splits_transaction_lines(stock_sessions):
    async with stock_sessions() as db:
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        item = Item(
            id="item-a", name="Film", category=category, is_serialized=False,
            is_lot_tracked=True, has_expiry=True,
        )
        location = Location(id="loc-a", code="A", name="Location A")
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        now = datetime.now(timezone.utc)
        first = StockLot(
            id="lot-first", item=item, location=location, lot_number="FIRST",
            quantity_on_hand=2, quantity_reserved=0,
            expiry_date=date.today() + timedelta(days=10), received_at=now,
        )
        second = StockLot(
            id="lot-second", item=item, location=location, lot_number="SECOND",
            quantity_on_hand=5, quantity_reserved=0,
            expiry_date=date.today() + timedelta(days=30), received_at=now,
        )
        db.add_all([
            category, item, location, user, first, second,
            Stock(
                id="stock-a", item=item, location=location, quantity_on_hand=7,
                quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0,
            ),
        ])
        await db.commit()

        result = await TransactionService(db).process_issue(
            IssueRequest(
                location_id=location.id,
                line_items=[IssueLineItem(item_id=item.id, quantity=4)],
            ),
            user_id=user.id,
        )
        transactions = list((await db.execute(
            select(Transaction)
            .where(Transaction.id.in_(result["transaction_ids"]))
            .order_by(Transaction.lot_id)
        )).scalars().all())
        await db.refresh(first)
        await db.refresh(second)
        assert [(txn.lot_id, txn.quantity) for txn in transactions] == [
            ("lot-first", 2), ("lot-second", 2),
        ]
        assert first.quantity_on_hand == 0
        assert second.quantity_on_hand == 3


@pytest.mark.asyncio
async def test_expired_lot_cannot_be_issued(stock_sessions):
    async with stock_sessions() as db:
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        item = Item(
            id="item-a", name="Film", category=category, is_serialized=False,
            is_lot_tracked=True, has_expiry=True,
        )
        location = Location(id="loc-a", code="A", name="Location A")
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        lot = StockLot(
            id="lot-expired", item=item, location=location, lot_number="EXPIRED",
            quantity_on_hand=3, quantity_reserved=0,
            expiry_date=date.today() - timedelta(days=1),
            received_at=datetime.now(timezone.utc),
        )
        db.add_all([
            category, item, location, user, lot,
            Stock(
                id="stock-a", item=item, location=location, quantity_on_hand=3,
                quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0,
            ),
        ])
        await db.commit()
        with pytest.raises(BadRequestError, match="expired"):
            await TransactionService(db).process_issue(
                IssueRequest(
                    location_id=location.id,
                    line_items=[IssueLineItem(
                        item_id=item.id, quantity=1, lot_id=lot.id,
                    )],
                ),
                user_id=user.id,
            )
