"""Item duplicate warnings and immutable historical-definition tests."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.dependencies import get_db
from app.core.security import hash_password
from app.db.base import Base
from app.main import create_application
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def item_client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as db:
        category_type = CategoryType(
            id="type-a", key="consumable", name="Consumable", stock_behavior="quantity"
        )
        category = Category(
            id="category-a", name="Consumables", category_type=category_type,
            stock_behavior="quantity", is_active=True,
        )
        other_category = Category(
            id="category-b", name="Accessories", category_type=category_type,
            stock_behavior="quantity", is_active=True,
        )
        location = Location(id="loc-a", code="A", name="Location A", is_active=True)
        admin = User(
            id="admin-a", email="admin-a@example.com", name="Admin A",
            password_hash=hash_password("Admin@123"), role=UserRole.ADMIN, is_active=True,
        )
        item = Item(
            id="item-a", name="Pressure Gauge", sku=None, manufacturer="Acme",
            model="PG-10", category=category, unit_of_measure="EA",
            asset_type="consumable", is_serialized=False, is_active=True,
        )
        stock = Stock(
            id="stock-a", item=item, location=location, quantity_on_hand=2,
            quantity_reserved=0, quantity_on_order=0, min_level=0,
            reorder_point=0, is_active=True,
        )
        db.add_all([category_type, category, other_category, location, admin, item, stock])
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
        yield client, headers

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_suggestions_match_normalized_identity(item_client):
    client, headers = item_client
    response = await client.get(
        "/api/v1/items/duplicate-suggestions",
        params={"name": " pressure gauge ", "manufacturer": "ACME", "model": "pg-10"},
        headers=headers,
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == ["item-a"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"unit_of_measure": "KG"},
    {"category_id": "category-b"},
    {"is_lot_tracked": True},
])
async def test_historical_item_definition_cannot_be_changed(item_client, payload):
    client, headers = item_client
    response = await client.patch("/api/v1/items/item-a", json=payload, headers=headers)

    assert response.status_code == 409
    assert "inventory history exists" in response.text


@pytest.mark.asyncio
async def test_product_with_current_stock_cannot_be_deactivated(item_client):
    client, headers = item_client
    response = await client.delete("/api/v1/items/item-a", headers=headers)

    assert response.status_code == 409
    assert "current stock" in response.text
