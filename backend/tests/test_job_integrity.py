"""Job completion and assignee identity regression tests."""

from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.job import Job, JobStatus
from app.models.location import Location
from app.models.user import User, UserRole
from app.services.job_service import JobService


@pytest_asyncio.fixture
async def job_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        location = Location(id="job-location", code="JOB", name="Job Location", is_active=True)
        other = Location(id="other-location", code="OTHER", name="Other", is_active=True)
        assignee = User(
            id="job-user", email="job.user@example.com", name="Job User",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[location],
        )
        same_name = User(
            id="same-name-user", email="same.name@example.com", name="Job User",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[other],
        )
        db.add_all([location, other, assignee, same_name])
        await db.commit()
        yield db, location, other, assignee, same_name
    await engine.dispose()


async def _job(service, location, assignee, total=10):
    return await service.create_job(
        job_date=date.today(), customer="Customer", job_name="Inspection",
        method="rt", quantity=10, total=total, person_name="Ignored legacy name",
        assigned_to_id=assignee.id, location_id=location.id,
    )


@pytest.mark.asyncio
async def test_completion_requires_balanced_explicit_cut_film_count(job_context):
    db, location, _, assignee, _ = job_context
    service = JobService(db)
    job = await _job(service, location, assignee)

    with pytest.raises(BadRequestError, match="Totals do not match"):
        await service.complete_job(job.id, assignee.id, 5, 2, "not parsed", 1)

    unchanged = await service.get_by_id(job.id)
    assert unchanged.status == JobStatus.HOLD
    assert unchanged.accepted is None


@pytest.mark.asyncio
async def test_balanced_completion_stores_numeric_count(job_context):
    db, location, _, assignee, _ = job_context
    service = JobService(db)
    job = await _job(service, location, assignee)

    completed = await service.complete_job(job.id, assignee.id, 5, 2, "three damaged films", 3)

    assert completed.status == JobStatus.COMPLETED
    assert completed.cut_films_count == 3
    assert completed.completion_total == 10
    assert completed.is_validated is True


@pytest.mark.asyncio
async def test_assignee_must_be_active_and_belong_to_location(job_context):
    db, location, _, _, wrong_assignee = job_context
    service = JobService(db)

    with pytest.raises(BadRequestError, match="does not belong"):
        await _job(service, location, wrong_assignee)


@pytest.mark.asyncio
async def test_eligibility_uses_user_id_not_duplicate_display_name(job_context):
    db, location, _, assignee, same_name = job_context
    service = JobService(db)
    blocked_job = await _job(service, location, assignee)
    blocked_job.status = JobStatus.COMPLETED
    blocked_job.is_validated = False
    await db.commit()

    assert await service.can_issue_new_job(assigned_to_id=assignee.id) is False
    assert await service.can_issue_new_job(assigned_to_id=same_name.id) is True
