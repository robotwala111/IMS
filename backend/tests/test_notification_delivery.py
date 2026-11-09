"""Durable notification outbox and reminder deduplication tests."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.notification import NotificationStatus
from app.services.notification_service import NotificationService
from app.services.scheduler import SchedulerService


class FakeEmailService:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.results)


@pytest_asyncio.fixture
async def notification_db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        yield db
    await engine.dispose()


@pytest.mark.asyncio
async def test_failed_email_is_persisted_and_retried_successfully(notification_db):
    service = NotificationService(notification_db)
    notification = await service.enqueue_email(
        recipient_emails=["manager@example.com"], notification_type="system_alert",
        subject="Action required", body_html="<p>Please review</p>",
        body_text="Please review", dedup_key="delivery:test:1",
    )
    failing_provider = FakeEmailService([False])
    result = await service.process_email_outbox(email_service=failing_provider)
    await notification_db.refresh(notification)

    assert result == {"claimed": 1, "sent": 0, "failed": 1}
    assert notification.status == NotificationStatus.FAILED
    assert notification.retry_count == 1
    assert notification.error_message
    assert notification.scheduled_at is not None

    notification.scheduled_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await notification_db.commit()
    successful_provider = FakeEmailService([True])
    result = await service.process_email_outbox(email_service=successful_provider)
    await notification_db.refresh(notification)

    assert result == {"claimed": 1, "sent": 1, "failed": 0}
    assert notification.status == NotificationStatus.SENT
    assert notification.retry_count == 2
    assert notification.sent_at is not None
    assert notification.error_message is None


@pytest.mark.asyncio
async def test_deduplication_key_suppresses_duplicate_reminder(notification_db):
    service = NotificationService(notification_db)
    first = await service.enqueue_email(
        recipient_emails=["manager@example.com"], notification_type="calibration_due",
        subject="Calibration due", body_html="<p>Due</p>",
        dedup_key="calibration:asset-1:2026-08-14",
    )
    duplicate = await service.enqueue_email(
        recipient_emails=["manager@example.com"], notification_type="calibration_due",
        subject="Calibration due again", body_html="<p>Duplicate</p>",
        dedup_key="calibration:asset-1:2026-08-14",
    )
    assert duplicate.id == first.id
    assert duplicate.subject == "Calibration due"


@pytest.mark.asyncio
async def test_sent_email_is_not_claimed_again(notification_db):
    service = NotificationService(notification_db)
    await service.enqueue_email(
        recipient_emails=["manager@example.com"], notification_type="transfer_request",
        subject="Transfer", body_html="<p>Transfer</p>", dedup_key="transfer:1",
    )
    provider = FakeEmailService([True])
    await service.process_email_outbox(email_service=provider)
    second = await service.process_email_outbox(email_service=FakeEmailService([]))
    assert second == {"claimed": 0, "sent": 0, "failed": 0}
    assert len(provider.calls) == 1


def test_scheduler_registers_email_outbox_worker():
    scheduler = SchedulerService()
    scheduler._register_default_tasks()
    task = scheduler._tasks["email_outbox_delivery"]
    assert task.interval_seconds == 60
    assert task.enabled is True

