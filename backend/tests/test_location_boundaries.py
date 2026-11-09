"""Location deactivation dependency and transfer-selector endpoint tests."""

from datetime import date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.dependencies import get_db
from app.core.security import hash_password
from app.db.base import Base
from app.main import create_application
from app.models.asset import AssetStatus, SerializedAsset
from app.models.category import Category
from app.models.employee import Employee
from app.models.item import Item
from app.models.location import Location
from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole
from app.services.location_service import LocationService


@pytest_asyncio.fixture
async def location_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine, sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_location_deactivation_reports_every_active_dependency(location_context):
    _, sessions = location_context
    async with sessions() as db:
        location = Location(id="loc-a", code="A", name="Location A", is_active=True)
        other = Location(id="loc-b", code="B", name="Location B", is_active=True)
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        category = Category(id="category-a", name="Category A", stock_behavior="quantity")
        item = Item(
            id="item-a", name="Item A", category=category, asset_type="equipment",
            is_serialized=True, is_active=True,
        )
        db.add_all([
            location, other, user, category, item,
            SerializedAsset(
                id="asset-a", item=item, location=location, serial_number="SER-A",
                status=AssetStatus.IN_SERVICE, acquired_at=date.today(),
            ),
            Employee(id="employee-a", name="Employee A", location=location, is_active=True),
            Transfer(
                id="transfer-a", transfer_number="TR-A", from_location_id=location.id,
                to_location_id=other.id, status=TransferStatus.REQUESTED,
                requested_date=datetime.utcnow(), requested_by_id=user.id,
                assigned_to_id=user.id, transfer_type="consumable",
            ),
            PurchaseIndent(
                id="pi-a", indent_number="PI-A", requested_by_location_id=location.id,
                supplying_location_id=other.id, requested_by_id=user.id,
                indent_date=datetime.utcnow(), status=PurchaseIndentStatus.APPROVED,
            ),
        ])
        await db.commit()

        blockers = await LocationService(db).get_deactivation_blockers(location.id)

        assert set(blockers) == {
            "serialized assets", "active employees", "pending transfers",
            "active purchase indents",
        }


@pytest.mark.asyncio
async def test_completed_or_inactive_dependencies_do_not_block_deactivation(location_context):
    _, sessions = location_context
    async with sessions() as db:
        location = Location(id="loc-a", code="A", name="Location A", is_active=True)
        other = Location(id="loc-b", code="B", name="Location B", is_active=True)
        user = User(
            id="user-a", email="user-a@example.com", name="User A", password_hash="unused",
            role=UserRole.LOCATION_MANAGER, is_active=True, assigned_locations=[location],
        )
        db.add_all([
            location, other, user,
            Employee(id="employee-a", name="Employee A", location=location, is_active=False),
            Transfer(
                id="transfer-a", transfer_number="TR-A", from_location_id=location.id,
                to_location_id=other.id, status=TransferStatus.RECEIVED,
                requested_date=datetime.utcnow(), requested_by_id=user.id,
                transfer_type="consumable",
            ),
            PurchaseIndent(
                id="pi-a", indent_number="PI-A", requested_by_location_id=location.id,
                supplying_location_id=other.id, requested_by_id=user.id,
                indent_date=datetime.utcnow(), status=PurchaseIndentStatus.FULFILLED,
            ),
        ])
        await db.commit()

        assert await LocationService(db).get_deactivation_blockers(location.id) == []


@pytest.mark.asyncio
async def test_transfer_source_and_destination_endpoints_for_location_manager(location_context):
    _, sessions = location_context
    async with sessions() as db:
        locations = [
            Location(id=f"loc-{number}", code=f"LOC-{number:04d}", name=f"Location {number}", is_active=True)
            for number in range(1, 8)
        ]
        inactive = Location(id="loc-removed", code="OLD", name="Removed", is_active=False)
        manager = User(
            id="manager-mlr", email="dummy.mlr@ndt.com", name="MLR Manager",
            password_hash=hash_password("dummy@123"), role=UserRole.LOCATION_MANAGER,
            is_active=True, assigned_locations=[locations[5]],
        )
        db.add_all([*locations, inactive, manager])
        await db.commit()

    app = create_application()

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/v1/auth/login", json={
            "email": "dummy.mlr@ndt.com", "password": "dummy@123",
        })
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        sources = await client.get("/api/v1/locations/transfer-sources", headers=headers)
        destinations = await client.get(
            "/api/v1/locations/transfer-destinations", headers=headers
        )

        assert sources.status_code == destinations.status_code == 200
        assert {row["id"] for row in sources.json()} == {f"loc-{number}" for number in range(1, 8)}
        assert [row["id"] for row in destinations.json()] == ["loc-6"]


@pytest.mark.asyncio
async def test_both_location_deactivation_routes_enforce_dependency_guard(location_context):
    _, sessions = location_context
    async with sessions() as db:
        location = Location(id="loc-a", code="A", name="Location A", is_active=True)
        admin = User(
            id="admin-a", email="admin-a@example.com", name="Admin A",
            password_hash=hash_password("Admin@123"), role=UserRole.ADMIN, is_active=True,
        )
        employee = Employee(
            id="employee-a", name="Employee A", location=location, is_active=True
        )
        db.add_all([location, admin, employee])
        await db.commit()

    app = create_application()

    async def override_db():
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login = await client.post("/api/v1/auth/login", json={
            "email": "admin-a@example.com", "password": "Admin@123",
        })
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        patched = await client.patch(
            "/api/v1/locations/loc-a", headers=headers, json={"is_active": False}
        )
        deleted = await client.delete("/api/v1/locations/loc-a", headers=headers)

        assert patched.status_code == 409
        assert deleted.status_code == 409
        assert "active employees" in patched.text
        assert "active employees" in deleted.text
