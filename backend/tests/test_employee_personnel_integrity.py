"""Employee and personnel-record integrity regression tests."""

from datetime import date

import pytest
import pytest_asyncio
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import BadRequestError
from app.db.base import Base
from app.models.employee import Employee
from app.models.employee_record import EmployeeRecord, EmployeeRecordType
from app.models.location import Location
from app.models.user import User, UserRole
from app.schemas.employee_record import EmployeeRecordCreate, EmployeeRecordUpdate
from app.services.employee_record_service import EmployeeRecordService


@pytest_asyncio.fixture
async def personnel_context():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as db:
        location = Location(id="personnel-location", code="PER", name="Personnel", is_active=True)
        user = User(
            id="personnel-user", email="person@example.com", name="Login Person",
            password_hash="unused", role=UserRole.LOCATION_MANAGER, is_active=True,
            assigned_locations=[location],
        )
        employee = Employee(
            id="personnel-employee", name="Field Person", employee_code="EMP-1",
            location=location, is_active=True,
        )
        db.add_all([location, user, employee])
        await db.commit()
        yield db, user, employee
    await engine.dispose()


def test_create_rejects_expiry_before_issue_for_every_record_type():
    for record_type in EmployeeRecordType:
        with pytest.raises(PydanticValidationError, match="Expiry date cannot be before"):
            EmployeeRecordCreate(
                user_id="user", record_type=record_type, title="Record",
                issue_date=date(2026, 2, 2), expiry_date=date(2026, 2, 1),
            )


def test_update_rejects_expiry_before_issue():
    with pytest.raises(PydanticValidationError, match="Expiry date cannot be before"):
        EmployeeRecordUpdate(
            issue_date=date(2026, 2, 2), expiry_date=date(2026, 2, 1)
        )


@pytest.mark.asyncio
async def test_duplicate_certificate_for_same_person_is_rejected(personnel_context):
    db, user, _ = personnel_context
    service = EmployeeRecordService(db)
    db.add(EmployeeRecord(
        id="record-one", user_id=user.id,
        record_type=EmployeeRecordType.PERSONAL_QUALIFICATION,
        title="Level II", certificate_number=" CERT-100 ", issuer="Institute",
    ))
    await db.commit()

    with pytest.raises(BadRequestError, match="already exists"):
        await service.ensure_not_duplicate(
            user_id=user.id, employee_id=None,
            record_type=EmployeeRecordType.PERSONAL_QUALIFICATION,
            title="Different title", certificate_number="cert-100", issuer="Other",
        )


@pytest.mark.asyncio
async def test_duplicate_uncoded_qualification_is_rejected(personnel_context):
    db, _, employee = personnel_context
    service = EmployeeRecordService(db)
    db.add(EmployeeRecord(
        id="record-two", employee_id=employee.id,
        record_type=EmployeeRecordType.PERSONAL_QUALIFICATION,
        title=" UT Level II ", issuer="ASNT",
    ))
    await db.commit()

    with pytest.raises(BadRequestError, match="already exists"):
        await service.ensure_not_duplicate(
            user_id=None, employee_id=employee.id,
            record_type=EmployeeRecordType.PERSONAL_QUALIFICATION,
            title="ut level ii", certificate_number=None, issuer=" asnt ",
        )


@pytest.mark.asyncio
async def test_record_owner_can_switch_symmetrically(personnel_context):
    db, user, employee = personnel_context
    service = EmployeeRecordService(db)
    record = EmployeeRecord(
        id="record-switch", user_id=user.id,
        record_type=EmployeeRecordType.PERSONAL_EXPERIENCE, title="Experience",
    )
    db.add(record)
    await db.commit()

    updated = await service.update(record.id, user_id=None, employee_id=employee.id)
    assert updated.user_id is None
    assert updated.employee_id == employee.id

    updated = await service.update(record.id, user_id=user.id, employee_id=None)
    assert updated.user_id == user.id
    assert updated.employee_id is None

