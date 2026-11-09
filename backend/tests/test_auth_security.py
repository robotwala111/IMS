"""Authentication lifecycle and token-replay regression tests."""

from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.v1.dependencies import get_db
from app.core.config import settings
from app.core.exceptions import AuthenticationError
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.main import create_application
from app.models.user import User, UserRole
from app.services.auth_token_service import AuthTokenService


@pytest_asyncio.fixture
async def auth_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessions() as session:
        session.add_all([
            User(
                id="active-user",
                email="active@example.com",
                name="Active User",
                password_hash=hash_password("Valid@123"),
                role=UserRole.ADMIN,
                is_active=True,
            ),
            User(
                id="disabled-user",
                email="disabled@example.com",
                name="Disabled User",
                password_hash=hash_password("Valid@123"),
                role=UserRole.LOCATION_MANAGER,
                is_active=False,
            ),
        ])
        await session.commit()

    app = create_application()

    async def override_db():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, sessions

    await engine.dispose()


@pytest.mark.asyncio
async def test_login_logout_and_disabled_user(auth_context):
    client, _ = auth_context
    disabled = await client.post("/api/v1/auth/login", json={
        "email": "disabled@example.com", "password": "Valid@123"
    })
    assert disabled.status_code == 401

    login = await client.post("/api/v1/auth/login", json={
        "email": "active@example.com", "password": "Valid@123"
    })
    assert login.status_code == 200
    access = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access}"}
    assert (await client.get("/api/v1/locations/summary", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/auth/logout", headers=headers, json={})).status_code == 200
    assert (await client.get("/api/v1/locations/summary", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotation_rejects_old_token(auth_context):
    client, _ = auth_context
    login = await client.post("/api/v1/auth/login", json={
        "email": "active@example.com", "password": "Valid@123"
    })
    old_refresh = login.json()["refresh_token"]
    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401


@pytest.mark.asyncio
async def test_password_reset_is_single_use_and_revokes_sessions(auth_context):
    client, sessions = auth_context
    login = await client.post("/api/v1/auth/login", json={
        "email": "active@example.com", "password": "Valid@123"
    })
    old_access = login.json()["access_token"]
    async with sessions() as session:
        token = await AuthTokenService(session).issue_password_reset("active-user")

    payload = {"token": token, "new_password": "Changed@123", "confirm_password": "Changed@123"}
    assert (await client.post("/api/v1/auth/reset-password", json=payload)).status_code == 200
    assert (await client.post("/api/v1/auth/reset-password", json=payload)).status_code == 401
    headers = {"Authorization": f"Bearer {old_access}"}
    assert (await client.get("/api/v1/locations/summary", headers=headers)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json={
        "email": "active@example.com", "password": "Changed@123"
    })).status_code == 200


@pytest.mark.asyncio
async def test_account_locks_after_configured_failures(auth_context):
    client, _ = auth_context
    for _ in range(settings.MAX_LOGIN_ATTEMPTS):
        response = await client.post("/api/v1/auth/login", json={
            "email": "active@example.com", "password": "Wrong@123"
        })
        assert response.status_code == 401
        assert "remaining_attempts" not in response.text
    locked = await client.post("/api/v1/auth/login", json={
        "email": "active@example.com", "password": "Valid@123"
    })
    assert locked.status_code == 401
    assert "temporarily locked" in locked.text


def test_expired_access_token_is_rejected():
    token = create_access_token(
        subject="active-user",
        additional_claims={"sid": "session-id"},
        expires_delta=timedelta(seconds=-1),
    )
    from app.core.security import validate_access_token
    with pytest.raises(AuthenticationError):
        validate_access_token(token)


@pytest.mark.asyncio
async def test_auth_endpoint_rate_limit_returns_429(auth_context, monkeypatch):
    client, _ = auth_context
    monkeypatch.setattr(settings, "RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE", 3)
    payload = {"email": "unknown@example.com", "password": "Wrong@123"}
    for _ in range(3):
        assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401
    limited = await client.post("/api/v1/auth/login", json=payload)
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
