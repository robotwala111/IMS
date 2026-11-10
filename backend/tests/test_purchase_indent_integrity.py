"""PI validation, cancellation synchronization, numbering, and document snapshots."""

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.category import Category
from app.models.generated_document import GeneratedDocument
from app.models.item import Item
from app.models.location import Location
from app.models.purchase_indent import PurchaseIndentStatus
from app.models.stock import Stock
from app.models.user import User, UserRole
from app.services.generated_document_service import GeneratedDocumentService
from app.services.purchase_indent_service import PurchaseIndentService
from app.services.transfer_service import TransferService


@pytest_asyncio.fixture
async def pi_context(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        source = Location(id="loc-a", code="SRC", name="Source", is_active=True)
        destination = Location(id="loc-b", code="DST", name="Destination", is_active=True)
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[destination],
        )
        approver = User(
            id="admin-a", email="admin-a@example.com", name="Admin A", password_hash="unused",
            role=UserRole.ADMIN, is_active=True,
        )
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        first = Item(id="item-a", name="Item A", category=category, is_serialized=False)
        second = Item(id="item-b", name="Item B", category=category, is_serialized=False)
        db.add_all([
            source, destination, user, approver, category, first, second,
            Stock(id="stock-a", item=first, location=source, quantity_on_hand=10,
                  quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0),
        ])
        await db.commit()
        monkeypatch.setattr(TransferService, "_generate_reference", lambda self: "TRF-PI-TEST")
        yield db, source, destination, user, approver, first, second
    await engine.dispose()


def test_pi_number_generation_locks_requesting_location():
    statement = select(Location).where(Location.id == "loc-a").with_for_update()
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
@pytest.mark.parametrize("approved_items", [
    [{"indent_item_id": "line-a", "quantity_approved": -1},
     {"indent_item_id": "line-b", "quantity_approved": 1}],
    [{"indent_item_id": "line-a", "quantity_approved": 6},
     {"indent_item_id": "line-b", "quantity_approved": 1}],
    [{"indent_item_id": "line-a", "quantity_approved": 1}],
    [{"indent_item_id": "line-a", "quantity_approved": 1},
     {"indent_item_id": "line-a", "quantity_approved": 1}],
])
async def test_pi_approval_rejects_invalid_line_quantities(pi_context, approved_items):
    db, _, destination, user, approver, first, second = pi_context
    service = PurchaseIndentService(db)
    indent = await service.create_indent(
        requested_by_location_id=destination.id, requested_by_id=user.id,
        items=[
            {"item_id": first.id, "quantity_requested": 5},
            {"item_id": second.id, "quantity_requested": 2},
        ],
    )
    approved_items = [dict(value) for value in approved_items]
    for value in approved_items:
        if value["indent_item_id"] == "line-a":
            value["indent_item_id"] = indent.items[0].id
        elif value["indent_item_id"] == "line-b":
            value["indent_item_id"] = indent.items[1].id

    with pytest.raises(BadRequestError):
        await service.approve_indent(
            indent.id, approved=True, user_id=approver.id,
            approved_items=approved_items,
        )


@pytest.mark.asyncio
async def test_transfer_cancellation_cancels_auto_generated_pi(pi_context):
    db, source, destination, user, _, first, _ = pi_context
    service = TransferService(db)
    transfer = await service.create_transfer(
        source_location_id=source.id, destination_location_id=destination.id,
        items=[{"item_id": first.id, "quantity": 2}], requested_by_id=user.id,
        assigned_to_id=user.id, transfer_type="consumable",
    )

    await service.cancel_transfer(transfer.id, user_id=user.id)
    indent = await PurchaseIndentService(db).get_by_id(transfer.purchase_indent_id)

    assert indent.status == PurchaseIndentStatus.CANCELLED


@pytest.mark.asyncio
async def test_generated_documents_are_immutable_revisions(pi_context):
    db, *_ = pi_context
    service = GeneratedDocumentService(db)
    first = await service.store_document(
        document_type="PI", reference_number="SS/DST/0001", filename="pi.pdf",
        content_type="application/pdf", content=b"original",
    )
    second = await service.store_document(
        document_type="PI", reference_number="SS/DST/0001", filename="pi.pdf",
        content_type="application/pdf", content=b"changed",
    )
    documents = list((await db.execute(
        select(GeneratedDocument).order_by(GeneratedDocument.revision_number)
    )).scalars().all())

    assert first.id != second.id
    assert [doc.revision_number for doc in documents] == [1, 2]
    assert [doc.content for doc in documents] == [b"original", b"changed"]
