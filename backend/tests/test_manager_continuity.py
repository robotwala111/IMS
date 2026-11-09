"""Regression tests for Location Manager staffing and transfer ownership guards."""

from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.endpoints.users import enforce_manager_continuity
from app.core.exceptions import ConflictError
from app.db.base import Base
from app.models.location import Location
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def manager_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as db:
        location = Location(id="loc-a", code="A", name="Location A", is_active=True)
        other_location = Location(id="loc-b", code="B", name="Location B", is_active=True)
        manager = User(
            id="manager-a", email="manager-a@example.com", name="Manager A",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[location],
        )
        db.add_all([location, other_location, manager])
        await db.commit()
        yield db, manager, location, other_location

    await engine.dispose()


def add_backup(db, location):
    backup = User(
        id=f"backup-{location.id}", email=f"backup-{location.id}@example.com",
        name="Backup Manager", password_hash="unused",
        role=UserRole.LOCATION_MANAGER, is_active=True,
        assigned_locations=[location],
    )
    db.add(backup)
    return backup


def add_pending_transfer(db, manager, source, destination):
    transfer = Transfer(
        id="pending-transfer", transfer_number="TR-PENDING",
        from_location_id=source.id, to_location_id=destination.id,
        status=TransferStatus.REQUESTED, requested_date=datetime.utcnow(),
        requested_by_id=manager.id, assigned_to_id=manager.id,
        destination_responsible_id=None, transfer_type="consumable",
    )
    db.add(transfer)
    return transfer


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["deactivate", "delete"])
async def test_last_active_manager_cannot_be_deactivated_or_deleted(manager_context, operation):
    db, manager, _, _ = manager_context

    with pytest.raises(ConflictError, match="only active Location Manager"):
        await enforce_manager_continuity(db, manager, manager.role, False, [])


@pytest.mark.asyncio
async def test_last_active_manager_location_cannot_be_removed(manager_context):
    db, manager, _, _ = manager_context

    with pytest.raises(ConflictError, match="only active Location Manager"):
        await enforce_manager_continuity(db, manager, manager.role, True, [])


@pytest.mark.asyncio
async def test_manager_location_removal_is_blocked_while_transfer_is_pending(manager_context):
    db, manager, location, destination = manager_context
    add_backup(db, location)
    add_pending_transfer(db, manager, location, destination)
    await db.commit()

    with pytest.raises(ConflictError, match="active transfer"):
        await enforce_manager_continuity(db, manager, manager.role, True, [])


@pytest.mark.asyncio
async def test_manager_deactivation_is_blocked_while_transfer_is_pending(manager_context):
    db, manager, location, destination = manager_context
    add_backup(db, location)
    add_pending_transfer(db, manager, location, destination)
    await db.commit()

    with pytest.raises(ConflictError, match="active transfer"):
        await enforce_manager_continuity(db, manager, manager.role, False, [])


@pytest.mark.asyncio
async def test_location_change_succeeds_after_transfer_reassignment(manager_context):
    db, manager, location, destination = manager_context
    backup = add_backup(db, location)
    transfer = add_pending_transfer(db, manager, location, destination)
    await db.commit()

    transfer.assigned_to_id = backup.id
    transfer.requested_by_id = backup.id
    await db.commit()

    await enforce_manager_continuity(db, manager, manager.role, True, [destination.id])


@pytest.mark.asyncio
async def test_role_change_succeeds_when_another_active_manager_covers_location(manager_context):
    db, manager, location, _ = manager_context
    add_backup(db, location)
    await db.commit()

    await enforce_manager_continuity(db, manager, UserRole.HEAD_OFFICE_MANAGER, True, [])
