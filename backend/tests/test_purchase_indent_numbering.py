"""Tests for location-based Purchase Indent reference numbering."""

import unittest
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.location import Location
from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus
from app.models.transfer import Transfer, TransferStatus
from app.models.user import User, UserRole
from app.services.purchase_indent_service import PurchaseIndentService
from app.services.transfer_service import TransferService


class PurchaseIndentNumberingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_number_uses_location_code_and_next_serial(self) -> None:
        async with self.sessions() as session:
            user = User(
                id="admin-1",
                email="admin@example.com",
                name="Admin",
                password_hash="hash",
                role=UserRole.ADMIN,
                is_active=True,
            )
            location = Location(
                id="loc-1", code="BLR", name="Bangalore", is_active=True
            )
            session.add_all([user, location])
            await session.flush()
            session.add_all(
                [
                    PurchaseIndent(
                        id="pi-old",
                        indent_number="PI-20260101010101-ABC123",
                        requested_by_location_id=location.id,
                        requested_by_id=user.id,
                        indent_date=datetime.now(timezone.utc),
                        status=PurchaseIndentStatus.SUBMITTED,
                    ),
                    PurchaseIndent(
                        id="pi-new",
                        indent_number="SS/BLR/0007",
                        requested_by_location_id=location.id,
                        requested_by_id=user.id,
                        indent_date=datetime.now(timezone.utc),
                        status=PurchaseIndentStatus.SUBMITTED,
                    ),
                ]
            )
            await session.commit()

            number = await PurchaseIndentService(session).generate_indent_number(location.id)

            self.assertEqual(number, "SS/BLR/0008")

    async def test_dc_number_uses_year_and_next_serial(self) -> None:
        async with self.sessions() as session:
            user = User(
                id="admin-dc",
                email="admin-dc@example.com",
                name="Admin",
                password_hash="hash",
                role=UserRole.ADMIN,
                is_active=True,
            )
            source = Location(id="loc-source", code="SRC", name="Source", is_active=True)
            destination = Location(
                id="loc-destination", code="DST", name="Destination", is_active=True
            )
            approved_at = datetime(2026, 7, 19, tzinfo=timezone.utc)
            existing = Transfer(
                id="transfer-existing",
                transfer_number="TRF-EXISTING",
                dc_number="SS/2026/0004",
                from_location_id=source.id,
                to_location_id=destination.id,
                status=TransferStatus.APPROVED,
                requested_date=approved_at,
                approved_at=approved_at,
                requested_by_id=user.id,
            )
            new_transfer = Transfer(
                id="transfer-new",
                transfer_number="TRF-NEW",
                from_location_id=source.id,
                to_location_id=destination.id,
                status=TransferStatus.APPROVED,
                requested_date=approved_at,
                approved_at=approved_at,
                requested_by_id=user.id,
            )
            session.add_all([user, source, destination, existing, new_transfer])
            await session.commit()

            number = await TransferService(session).ensure_dc_number(new_transfer)

            self.assertEqual(number, "SS/2026/0005")
            self.assertEqual(new_transfer.dc_number, number)
