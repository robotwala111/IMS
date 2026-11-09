"""Maintenance lifecycle integrity regression tests."""

from datetime import date, datetime, timedelta

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
from app.models.user import User, UserRole
from app.services.maintenance_service import MaintenanceService


@pytest_asyncio.fixture
async def maintenance_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        category_type = CategoryType(
            id="maintenance-type", key="equipment", name="Equipment",
            stock_behavior="serialized",
        )
        category = Category(
            id="maintenance-category", name="Equipment Category",
            category_type=category_type, stock_behavior="serialized", is_active=True,
        )
        item = Item(
            id="maintenance-item", name="Equipment", category=category,
            asset_type="equipment", is_serialized=True, is_active=True,
        )
        location = Location(
            id="maintenance-location", code="MAINT", name="Maintenance", is_active=True,
        )
        manager = User(
            id="maintenance-manager", email="maintenance@example.com", name="Manager",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[location],
        )
        asset = SerializedAsset(
            id="maintenance-asset", item=item, serial_number="MAINT-001",
            location=location, status=AssetStatus.IN_SERVICE, acquired_at=date.today(),
        )
        db.add_all([category_type, category, item, location, manager, asset])
        await db.commit()
        yield db, asset, manager
    await engine.dispose()


async def _create(service, asset, manager, **overrides):
    values = {
        "asset_id": asset.id,
        "performed_by_id": manager.id,
        "maintenance_type": "preventive",
        "scheduled_at": datetime.utcnow() - timedelta(hours=1),
        "description": "Routine maintenance",
    }
    values.update(overrides)
    return await service.create(**values)


@pytest.mark.asyncio
async def test_prevents_overlapping_active_maintenance(maintenance_context):
    db, asset, manager = maintenance_context
    service = MaintenanceService(db)
    await _create(service, asset, manager)

    with pytest.raises(BadRequestError, match="overlapping maintenance"):
        await _create(service, asset, manager)


@pytest.mark.asyncio
async def test_prevents_overlapping_completed_maintenance_periods(maintenance_context):
    db, asset, manager = maintenance_context
    service = MaintenanceService(db)
    scheduled = datetime.utcnow() - timedelta(days=2)
    await _create(
        service, asset, manager, scheduled_at=scheduled,
        completed_at=scheduled + timedelta(hours=4), work_performed="First service",
    )

    with pytest.raises(BadRequestError, match="overlapping maintenance"):
        await _create(
            service, asset, manager, scheduled_at=scheduled + timedelta(hours=2),
            completed_at=scheduled + timedelta(hours=6), work_performed="Duplicate service",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [AssetStatus.RETIRED, AssetStatus.LOST])
async def test_terminal_assets_reject_new_maintenance(maintenance_context, status):
    db, asset, manager = maintenance_context
    asset.status = status
    await db.commit()

    with pytest.raises(BadRequestError, match=status.value):
        await _create(MaintenanceService(db), asset, manager)


@pytest.mark.asyncio
async def test_completed_maintenance_requires_work_details(maintenance_context):
    db, asset, manager = maintenance_context
    scheduled = datetime.utcnow() - timedelta(days=1)

    with pytest.raises(BadRequestError, match="Work performed"):
        await _create(
            MaintenanceService(db), asset, manager,
            scheduled_at=scheduled, completed_at=scheduled + timedelta(hours=1),
        )


@pytest.mark.asyncio
async def test_completion_cannot_precede_schedule(maintenance_context):
    db, asset, manager = maintenance_context
    scheduled = datetime.utcnow()

    with pytest.raises(BadRequestError, match="cannot be before"):
        await _create(
            MaintenanceService(db), asset, manager, scheduled_at=scheduled,
            completed_at=scheduled - timedelta(minutes=1), work_performed="Completed",
        )


@pytest.mark.asyncio
async def test_recurrence_must_follow_completion(maintenance_context):
    db, asset, manager = maintenance_context
    service = MaintenanceService(db)
    record = await _create(service, asset, manager)

    with pytest.raises(BadRequestError, match="Next maintenance due"):
        await service.complete(
            record.id, manager.id, "Serviced", result="passed",
            next_maintenance_due=datetime.utcnow() - timedelta(days=1),
        )


@pytest.mark.asyncio
async def test_successful_completion_and_preventive_recurrence(maintenance_context):
    db, asset, manager = maintenance_context
    service = MaintenanceService(db)
    record = await _create(service, asset, manager)
    next_due = datetime.utcnow() + timedelta(days=90)

    completed = await service.complete(
        record.id, manager.id, "Cleaned and inspected", result="passed",
        next_maintenance_due=next_due,
    )

    assert completed.completed_by_id == manager.id
    assert completed.completed_at is not None
    assert completed.next_maintenance_due == next_due
    assert completed.work_performed == "Cleaned and inspected"
