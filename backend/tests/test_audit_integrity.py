"""Append-only, signed audit trail regression tests."""

import json

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.logging import set_correlation_id
from app.db.base import Base
from app.models.audit import AuditLog
from app.services.archive_service import purge_archived_records
from app.services.audit_service import AuditService


@pytest_asyncio.fixture
async def audit_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        yield db, sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_entry_is_signed_correlated_and_has_standard_diff(audit_context):
    db, _ = audit_context
    set_correlation_id("audit-correlation-id")
    log = await AuditService(db).log_action(
        action="update", resource_type="test_resource", resource_id="resource-1",
        user_id=None, old_value={"status": "old", "unchanged": 1},
        new_value={"status": "new", "unchanged": 1},
    )

    assert log.correlation_id == "audit-correlation-id"
    assert log.has_valid_integrity_hash()
    assert json.loads(log.changes) == {"status": {"before": "old", "after": "new"}}
    assert await AuditService(db).verify_integrity() == {
        "total": 1, "valid": 1, "invalid_ids": []
    }


@pytest.mark.asyncio
async def test_orm_update_and_delete_are_blocked(audit_context):
    db, _ = audit_context
    log = await AuditService(db).log_action(
        action="create", resource_type="test_resource", resource_id="resource-1",
        user_id=None, new_value={"name": "Original"},
    )
    log_id = log.id
    log.action = "tampered"
    with pytest.raises(ValueError, match="append-only"):
        await db.commit()
    await db.rollback()

    log = await db.get(AuditLog, log_id)
    await db.delete(log)
    with pytest.raises(ValueError, match="append-only"):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_integrity_verification_detects_out_of_band_tampering(audit_context):
    db, _ = audit_context
    log = await AuditService(db).log_action(
        action="create", resource_type="test_resource", resource_id="resource-1",
        user_id=None, new_value={"name": "Original"},
    )
    log_id = log.id
    await db.execute(
        text("UPDATE audit_logs SET new_value = :value WHERE id = :id"),
        {"value": '{"name":"Tampered"}', "id": log_id},
    )
    await db.commit()
    db.expire_all()

    verification = await AuditService(db).verify_integrity()
    assert verification["invalid_ids"] == [log_id]
    assert verification["valid"] == 0


@pytest.mark.asyncio
async def test_archive_purge_retains_audit_evidence(audit_context):
    db, sessions = audit_context
    log = await AuditService(db).log_action(
        action="create", resource_type="test_resource", resource_id="resource-1",
        user_id=None,
    )
    result = await purge_archived_records(log.occurred_at, session_factory=sessions)
    assert result["audit_logs"] == 0
    async with sessions() as verification_db:
        assert (await verification_db.execute(select(AuditLog))).scalar_one().id == log.id
