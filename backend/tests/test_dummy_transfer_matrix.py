"""Full cross-location lifecycle matrix for all dummy Location Managers."""

import itertools

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock
from app.models.transfer import TransferStatus
from app.models.user import User, UserRole
from app.schemas.transfer import (
    ReceivedItemDetail,
    ShippedItemDetail,
    TransferReceiveRequest,
    TransferShipRequest,
)
from app.services.transfer_service import TransferService
from app.core.exceptions import BadRequestError


DUMMY_CODES = ("blr", "smg", "eshwar", "hubli", "cbt", "mlr", "jrg")


@pytest_asyncio.fixture
async def transfer_matrix_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as db:
        category_type = CategoryType(
            id="quantity-type", key="consumable", name="Consumable", stock_behavior="quantity"
        )
        category = Category(
            id="category", name="Matrix Category", category_type=category_type,
            stock_behavior="quantity", is_active=True,
        )
        item = Item(
            id="matrix-item", name="Matrix Item", sku=None, category=category,
            asset_type="consumable", is_serialized=False, is_active=True,
        )
        admin = User(
            id="matrix-admin", email="matrix-admin@example.com", name="Matrix Admin",
            password_hash="unused", role=UserRole.ADMIN, is_active=True,
        )
        managers = {}
        locations = {}
        db.add_all([category_type, category, item, admin])
        for code in DUMMY_CODES:
            location = Location(
                id=f"loc-{code}", code=code.upper(), name=f"{code.upper()} Location", is_active=True
            )
            manager = User(
                id=f"manager-{code}", email=f"dummy.{code}@ndt.com",
                name=f"Dummy {code.upper()} Manager", password_hash="unused",
                role=UserRole.LOCATION_MANAGER, is_active=True,
                assigned_locations=[location],
            )
            stock = Stock(
                id=f"stock-{code}", item=item, location=location,
                quantity_on_hand=100, quantity_reserved=0,
                quantity_on_order=0, min_level=0, reorder_point=0, is_active=True,
            )
            managers[code], locations[code] = manager, location
            db.add_all([location, manager, stock])
        await db.commit()
        yield db, admin, managers, locations, item

    await engine.dispose()


@pytest.mark.asyncio
async def test_every_dummy_account_cross_location_transfer_lifecycle(
    transfer_matrix_context, monkeypatch
):
    db, admin, managers, locations, item = transfer_matrix_context
    sequence = itertools.count(1)
    monkeypatch.setattr(
        TransferService, "_generate_reference",
        lambda self: f"TRF-MATRIX-{next(sequence):04d}",
    )
    service = TransferService(db)
    tested_pairs = 0

    for destination_code, source_code in itertools.permutations(DUMMY_CODES, 2):
        destination_manager = managers[destination_code]
        source_manager = managers[source_code]
        source = locations[source_code]
        destination = locations[destination_code]

        # Permission contract: requester/receiver owns only the destination;
        # source handler owns the source; company admin approves.
        assert destination_manager.has_location_access(destination.id)
        assert not destination_manager.has_location_access(source.id)
        assert source_manager.has_location_access(source.id)
        assert admin.has_all_location_access

        source_stock = (await db.execute(select(Stock).where(
            Stock.item_id == item.id, Stock.location_id == source.id
        ))).scalar_one()
        destination_stock = (await db.execute(select(Stock).where(
            Stock.item_id == item.id, Stock.location_id == destination.id
        ))).scalar_one()
        source_before = source_stock.quantity_on_hand
        destination_before = destination_stock.quantity_on_hand

        transfer = await service.create_transfer(
            source_location_id=source.id,
            destination_location_id=destination.id,
            items=[{"item_id": item.id, "quantity": 1}],
            requested_by_id=destination_manager.id,
            assigned_to_id=source_manager.id,
            destination_responsible_id=destination_manager.id,
            requires_approval=True,
            transfer_type="consumable",
        )
        assert transfer.status == TransferStatus.REQUESTED
        assert source_stock.quantity_on_hand == source_before
        assert source_stock.quantity_reserved == 1

        transfer = await service.approve_transfer(
            transfer.id, approved=True, user_id=admin.id
        )
        assert transfer.status == TransferStatus.APPROVED
        assert transfer.approved_by_id == admin.id

        transfer = await service.get_by_id(transfer.id)
        line = transfer.items[0]
        line_id = line.id
        transfer = await service.ship_transfer(
            transfer.id,
            TransferShipRequest(shipped_items=[
                    ShippedItemDetail(transfer_item_id=line_id, quantity_shipped=1)
            ]),
            user_id=source_manager.id,
        )
        assert transfer.status == TransferStatus.IN_TRANSIT
        assert transfer.shipped_by_id == source_manager.id
        assert source_stock.quantity_on_hand == source_before - 1
        assert source_stock.quantity_reserved == 0

        transfer = await service.receive_transfer(
            transfer.id,
            TransferReceiveRequest(received_items=[
                ReceivedItemDetail(transfer_item_id=line_id, quantity_received=1)
            ]),
            user_id=destination_manager.id,
        )
        assert transfer.status == TransferStatus.RECEIVED
        assert transfer.received_by_id == destination_manager.id
        assert destination_stock.quantity_on_hand == destination_before + 1
        tested_pairs += 1

    assert tested_pairs == len(DUMMY_CODES) * (len(DUMMY_CODES) - 1) == 42


@pytest.mark.asyncio
async def test_partial_ship_and_receive_can_continue_to_completion(
    transfer_matrix_context, monkeypatch
):
    db, admin, managers, locations, item = transfer_matrix_context
    monkeypatch.setattr(TransferService, "_generate_reference", lambda self: "TRF-PARTIAL")
    service = TransferService(db)
    source, destination = locations["blr"], locations["mlr"]
    source_manager, destination_manager = managers["blr"], managers["mlr"]
    source_stock = (await db.execute(select(Stock).where(
        Stock.item_id == item.id, Stock.location_id == source.id
    ))).scalar_one()
    destination_stock = (await db.execute(select(Stock).where(
        Stock.item_id == item.id, Stock.location_id == destination.id
    ))).scalar_one()

    transfer = await service.create_transfer(
        source_location_id=source.id, destination_location_id=destination.id,
        items=[{"item_id": item.id, "quantity": 10}],
        requested_by_id=destination_manager.id, assigned_to_id=source_manager.id,
        destination_responsible_id=destination_manager.id, transfer_type="consumable",
    )
    transfer = await service.approve_transfer(transfer.id, True, user_id=admin.id)
    transfer = await service.get_by_id(transfer.id)
    line_id = transfer.items[0].id

    transfer = await service.ship_transfer(
        transfer.id, TransferShipRequest(shipped_items=[ShippedItemDetail(
            transfer_item_id=line_id, quantity_shipped=6
        )]), user_id=source_manager.id,
    )
    assert transfer.status == TransferStatus.IN_TRANSIT
    assert source_stock.quantity_on_hand == 94
    assert source_stock.quantity_reserved == 4

    transfer = await service.receive_transfer(
        transfer.id, TransferReceiveRequest(received_items=[ReceivedItemDetail(
            transfer_item_id=line_id, quantity_received=4
        )]), user_id=destination_manager.id,
    )
    assert transfer.status == TransferStatus.PARTIALLY_RECEIVED
    assert destination_stock.quantity_on_hand == 104

    with pytest.raises(BadRequestError, match="Remaining: 4"):
        await service.ship_transfer(
            transfer.id, TransferShipRequest(shipped_items=[ShippedItemDetail(
                transfer_item_id=line_id, quantity_shipped=5
            )]), user_id=source_manager.id,
        )

    transfer = await service.ship_transfer(
        transfer.id, TransferShipRequest(shipped_items=[ShippedItemDetail(
            transfer_item_id=line_id, quantity_shipped=4
        )]), user_id=source_manager.id,
    )
    assert transfer.status == TransferStatus.PARTIALLY_RECEIVED
    assert source_stock.quantity_on_hand == 90
    assert source_stock.quantity_reserved == 0

    transfer = await service.receive_transfer(
        transfer.id, TransferReceiveRequest(received_items=[ReceivedItemDetail(
            transfer_item_id=line_id, quantity_received=6
        )]), user_id=destination_manager.id,
    )
    assert transfer.status == TransferStatus.RECEIVED
    transfer = await service.get_by_id(transfer.id)
    assert transfer.items[0].quantity_shipped == 10
    assert transfer.items[0].quantity_received == 10
    assert destination_stock.quantity_on_hand == 110


@pytest.mark.asyncio
async def test_damaged_and_lost_receipt_closes_transfer_without_inflating_stock(
    transfer_matrix_context, monkeypatch
):
    db, admin, managers, locations, item = transfer_matrix_context
    monkeypatch.setattr(TransferService, "_generate_reference", lambda self: "TRF-DISCREPANCY")
    service = TransferService(db)
    source, destination = locations["blr"], locations["mlr"]
    source_manager, destination_manager = managers["blr"], managers["mlr"]
    destination_stock = (await db.execute(select(Stock).where(
        Stock.item_id == item.id, Stock.location_id == destination.id
    ))).scalar_one()

    transfer = await service.create_transfer(
        source_location_id=source.id, destination_location_id=destination.id,
        items=[{"item_id": item.id, "quantity": 5}],
        requested_by_id=destination_manager.id, assigned_to_id=source_manager.id,
        destination_responsible_id=destination_manager.id, transfer_type="consumable",
    )
    transfer = await service.approve_transfer(transfer.id, True, user_id=admin.id)
    transfer = await service.get_by_id(transfer.id)
    line_id = transfer.items[0].id
    transfer = await service.ship_transfer(
        transfer.id,
        TransferShipRequest(shipped_items=[
            ShippedItemDetail(transfer_item_id=line_id, quantity_shipped=5)
        ]),
        user_id=source_manager.id,
    )
    transfer = await service.receive_transfer(
        transfer.id,
        TransferReceiveRequest(received_items=[ReceivedItemDetail(
            transfer_item_id=line_id, quantity_received=2,
            quantity_damaged=2, quantity_lost=1,
            condition_notes="Carton crushed; one unit missing in transit",
        )]),
        user_id=destination_manager.id,
    )
    transfer = await service.get_by_id(transfer.id)
    assert transfer.status == TransferStatus.RECEIVED
    assert transfer.items[0].quantity_received == 2
    assert transfer.items[0].quantity_damaged == 2
    assert transfer.items[0].quantity_lost == 1
    assert destination_stock.quantity_on_hand == 102
    assert "one unit missing" in transfer.receiving_notes


def test_transfer_discrepancy_requires_condition_notes():
    with pytest.raises(ValueError, match="Condition notes"):
        ReceivedItemDetail(
            transfer_item_id="line-a", quantity_received=0, quantity_damaged=1,
        )
