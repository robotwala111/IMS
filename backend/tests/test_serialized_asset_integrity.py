"""Serialized asset state, custody, and overlapping-transfer regression tests."""

from datetime import date, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.asset import AssetStatus, SerializedAsset
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock
from app.models.transfer import Transfer, TransferItem, TransferStatus
from app.models.user import User, UserRole
from app.schemas.transfer import ReceivedItemDetail, ShippedItemDetail, TransferReceiveRequest, TransferShipRequest
from app.services.asset_service import AssetService
from app.services.transfer_service import TransferService


def test_asset_status_transition_matrix():
    AssetService.validate_status_transition(AssetStatus.LOST, AssetStatus.IN_SERVICE)
    AssetService.validate_status_transition(AssetStatus.UNDER_CALIBRATION, AssetStatus.IN_SERVICE)
    with pytest.raises(BadRequestError):
        AssetService.validate_status_transition(AssetStatus.RETIRED, AssetStatus.IN_SERVICE)
    with pytest.raises(BadRequestError):
        AssetService.validate_status_transition(
            AssetStatus.UNDER_CALIBRATION, AssetStatus.UNDER_MAINTENANCE
        )


@pytest_asyncio.fixture
async def serialized_context(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        category_type = CategoryType(
            id="serialized-type", key="equipment", name="Equipment", stock_behavior="serialized"
        )
        category = Category(
            id="category-a", name="Equipment Category", category_type=category_type,
            stock_behavior="serialized", is_active=True,
        )
        item = Item(
            id="item-a", name="Equipment A", sku="EQ-A", category=category,
            asset_type="equipment", is_serialized=True, is_active=True,
        )
        source = Location(id="loc-a", code="A", name="Source", is_active=True)
        destination = Location(id="loc-b", code="B", name="Destination", is_active=True)
        source_manager = User(
            id="source-user", email="source@example.com", name="Source User",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[source],
        )
        destination_manager = User(
            id="destination-user", email="destination@example.com", name="Destination User",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[destination],
        )
        admin = User(
            id="admin", email="admin@example.com", name="Admin", password_hash="unused",
            role=UserRole.ADMIN, is_active=True,
        )
        asset = SerializedAsset(
            id="asset-a", item=item, serial_number="SER-A", location=source,
            status=AssetStatus.IN_SERVICE, acquired_at=date.today(),
        )
        stock = Stock(
            id="stock-a", item=item, location=source, quantity_on_hand=1,
            quantity_reserved=0, quantity_on_order=0, min_level=0, reorder_point=0,
        )
        db.add_all([
            category_type, category, item, source, destination, source_manager,
            destination_manager, admin, asset, stock,
        ])
        await db.commit()
        monkeypatch.setattr(TransferService, "_generate_reference", lambda self: "TRF-SERIAL-A")
        yield db, asset, source, destination, source_manager, destination_manager, admin, item
    await engine.dispose()


@pytest.mark.asyncio
async def test_active_transfer_blocks_direct_location_change(serialized_context):
    db, asset, source, destination, source_manager, destination_manager, _, item = serialized_context
    transfer = Transfer(
        id="transfer-a", transfer_number="TR-A", from_location_id=source.id,
        to_location_id=destination.id, status=TransferStatus.REQUESTED,
        requested_date=datetime.utcnow(), requested_by_id=destination_manager.id,
        assigned_to_id=source_manager.id, transfer_type="equipment",
    )
    transfer.items.append(TransferItem(
        id="line-a", item_id=item.id, quantity_requested=1,
        quantity_shipped=0, quantity_received=0, serial_numbers='["SER-A"]',
    ))
    db.add(transfer)
    await db.commit()

    with pytest.raises(BadRequestError, match="active transfer"):
        await AssetService(db).update_asset(asset.id, location_id=destination.id)


@pytest.mark.asyncio
async def test_serialized_chain_of_custody_and_overlap_protection(serialized_context):
    db, asset, source, destination, source_manager, destination_manager, admin, item = serialized_context
    service = TransferService(db)
    transfer = await service.create_transfer(
        source_location_id=source.id, destination_location_id=destination.id,
        items=[{"item_id": item.id, "quantity": 1, "serial_numbers": [asset.serial_number]}],
        requested_by_id=destination_manager.id, assigned_to_id=source_manager.id,
        destination_responsible_id=destination_manager.id, transfer_type="equipment",
    )
    assert transfer.status == TransferStatus.REQUESTED

    with pytest.raises(BadRequestError, match="already in an active transfer"):
        await service.create_transfer(
            source_location_id=source.id, destination_location_id=destination.id,
            items=[{"item_id": item.id, "quantity": 1, "serial_numbers": [asset.serial_number]}],
            requested_by_id=destination_manager.id, assigned_to_id=source_manager.id,
            transfer_type="equipment",
        )
    transfer = await service.approve_transfer(transfer.id, True, user_id=admin.id)
    transfer = await service.get_by_id(transfer.id)
    line_id = transfer.items[0].id
    await service.ship_transfer(
        transfer.id,
        TransferShipRequest(shipped_items=[ShippedItemDetail(
            transfer_item_id=line_id, quantity_shipped=1
        )]), user_id=source_manager.id,
    )
    received = await service.receive_transfer(
        transfer.id,
        TransferReceiveRequest(received_items=[ReceivedItemDetail(
            transfer_item_id=line_id, quantity_received=1
        )]), user_id=destination_manager.id,
    )
    await db.refresh(asset)

    assert received.status == TransferStatus.RECEIVED
    assert asset.location_id == destination.id
