"""Return linkage, quantity-limit, and idempotency regression tests."""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock
from app.models.transaction import Transaction, TransactionType
from app.models.user import User, UserRole
from app.schemas.transaction import ReturnLineItem, ReturnRequest
from app.services.transaction_service import TransactionService


@pytest_asyncio.fixture
async def return_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        item = Item(id="item-a", name="Item A", category=category, is_serialized=False)
        other_item = Item(id="item-b", name="Item B", category=category, is_serialized=False)
        location = Location(id="loc-a", code="A", name="Location A")
        other_location = Location(id="loc-b", code="B", name="Location B")
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        issue = Transaction(
            id="issue-a", transaction_type=TransactionType.ISSUE, item=item,
            location=location, quantity=5, reference_number="ISS-1", created_by=user,
            transaction_date=datetime.now(timezone.utc),
        )
        db.add_all([
            category, item, other_item, location, other_location, user, issue,
            Stock(id="stock-a", item=item, location=location, quantity_on_hand=5,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0),
            Stock(id="stock-b", item=other_item, location=location, quantity_on_hand=0,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0),
        ])
        await db.commit()
        yield db, user, item, other_item, location, other_location, issue
    await engine.dispose()


def return_request(issue, item, location, quantity, key=None):
    return ReturnRequest(
        location_id=location.id,
        idempotency_key=key,
        line_items=[ReturnLineItem(
            item_id=item.id, original_issue_id=issue.id, quantity=quantity,
        )],
    )


@pytest.mark.asyncio
async def test_return_links_to_original_issue(return_context):
    db, user, item, _, location, _, issue = return_context
    result = await TransactionService(db).process_return(
        return_request(issue, item, location, 2), user_id=user.id,
    )
    returned = await db.get(Transaction, result["transaction_ids"][0])
    assert returned.reference_type == "transaction"
    assert returned.reference_id == issue.id
    stock = (await db.execute(select(Stock).where(Stock.id == "stock-a"))).scalar_one()
    assert stock.quantity_on_hand == 7


@pytest.mark.asyncio
async def test_return_rejects_more_than_remaining_issue_quantity(return_context):
    db, user, item, _, location, _, issue = return_context
    service = TransactionService(db)
    await service.process_return(return_request(issue, item, location, 3), user_id=user.id)
    with pytest.raises(BadRequestError, match="Returnable: 2, Requested: 3"):
        await service.process_return(return_request(issue, item, location, 3), user_id=user.id)
    await db.rollback()
    stock = (await db.execute(select(Stock).where(Stock.id == "stock-a"))).scalar_one()
    assert stock.quantity_on_hand == 8


@pytest.mark.asyncio
async def test_return_rejects_item_or_location_not_matching_issue(return_context):
    db, user, _, other_item, location, other_location, issue = return_context
    service = TransactionService(db)
    with pytest.raises(BadRequestError, match="must match"):
        await service.process_return(return_request(issue, other_item, location, 1), user_id=user.id)
    with pytest.raises(BadRequestError, match="must match"):
        await service.process_return(return_request(issue, issue.item, other_location, 1), user_id=user.id)


@pytest.mark.asyncio
async def test_return_idempotency_key_does_not_add_stock_twice(return_context):
    db, user, item, _, location, _, issue = return_context
    request = return_request(issue, item, location, 2, key="return-request-1")
    service = TransactionService(db)
    first = await service.process_return(request, user_id=user.id)
    second = await service.process_return(request, user_id=user.id)
    assert second["transaction_ids"] == first["transaction_ids"]
    assert second["idempotent_replay"] is True
    stock = (await db.execute(select(Stock).where(Stock.id == "stock-a"))).scalar_one()
    return_count = (await db.execute(
        select(func.count()).select_from(Transaction).where(
            Transaction.transaction_type == TransactionType.RETURN
        )
    )).scalar_one()
    assert stock.quantity_on_hand == 7
    assert return_count == 1


@pytest.mark.asyncio
async def test_return_idempotency_key_rejects_different_payload(return_context):
    db, user, item, _, location, _, issue = return_context
    service = TransactionService(db)
    await service.process_return(
        return_request(issue, item, location, 1, key="return-request-1"), user_id=user.id,
    )
    with pytest.raises(BadRequestError, match="different return"):
        await service.process_return(
            return_request(issue, item, location, 2, key="return-request-1"), user_id=user.id,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("condition", ["damaged", "expired"])
async def test_non_serviceable_return_is_traced_without_increasing_usable_stock(
    return_context, condition,
):
    db, user, item, _, location, _, issue = return_context
    request = ReturnRequest(
        location_id=location.id,
        line_items=[ReturnLineItem(
            item_id=item.id, original_issue_id=issue.id, quantity=2,
            condition=condition,
        )],
    )
    result = await TransactionService(db).process_return(request, user_id=user.id)
    returned = await db.get(Transaction, result["transaction_ids"][0])
    stock = await db.get(Stock, "stock-a")
    assert returned.return_condition == condition
    assert stock.quantity_on_hand == 5


@pytest.mark.asyncio
async def test_idempotency_key_rejects_changed_return_condition(return_context):
    db, user, item, _, location, _, issue = return_context
    service = TransactionService(db)
    good = return_request(issue, item, location, 1, key="return-condition-1")
    await service.process_return(good, user_id=user.id)
    damaged = ReturnRequest(
        location_id=location.id, idempotency_key="return-condition-1",
        line_items=[ReturnLineItem(
            item_id=item.id, original_issue_id=issue.id, quantity=1,
            condition="damaged",
        )],
    )
    with pytest.raises(BadRequestError, match="different return"):
        await service.process_return(damaged, user_id=user.id)
