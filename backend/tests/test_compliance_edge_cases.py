"""Regression tests for Product-to-Compliance edge cases."""

import unittest
from datetime import date, datetime, timedelta, timezone

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.asset import AssetStatus, SerializedAsset
from app.models.calibration import CalibrationRecord
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.models.location import Location
from app.schemas.asset import (
    CalibrationRecordCreate,
    CalibrationSupplierTransactionCreate,
)
from app.services.transfer_service import TransferService


class ComplianceEdgeCaseTests(unittest.IsolatedAsyncioTestCase):
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

    def test_invalid_calibration_dates_are_rejected(self):
        today = date.today()
        with self.assertRaises(ValidationError):
            CalibrationRecordCreate(
                certificate_number="CERT-1",
                performed_at=today,
                due_at=today,
                performed_by="Lab",
            )

        with self.assertRaises(ValidationError):
            CalibrationSupplierTransactionCreate(
                asset_id="asset-1",
                sent_at=today,
                received_at=today - timedelta(days=1),
                supplier_name="Lab",
            )

    async def test_overview_uses_latest_same_day_record_and_omits_retired_assets(self):
        async with self.sessions() as session:
            category_type = CategoryType(
                id="instrument-type", key="instrument", name="Instrument",
                stock_behavior="serialized", is_active=True,
            )
            category = Category(
                id="instrument-category", name="Instrument",
                category_type_id=category_type.id,
                stock_behavior="serialized", is_active=True,
            )
            item = Item(
                id="instrument-item", sku="INST", name="Instrument",
                category_id=category.id, asset_type="instrument",
                is_serialized=True, requires_calibration=True, is_active=True,
            )
            location = Location(id="loc-1", code="LOC", name="Location", is_active=True)
            active = SerializedAsset(
                id="asset-active", item_id=item.id, serial_number="SER-A",
                location_id=location.id, acquired_at=date(2026, 1, 1),
                status=AssetStatus.IN_SERVICE,
            )
            retired = SerializedAsset(
                id="asset-retired", item_id=item.id, serial_number="SER-R",
                location_id=location.id, acquired_at=date(2026, 1, 1),
                status=AssetStatus.RETIRED,
            )
            session.add_all([category_type, category, item, location, active, retired])
            await session.flush()

            performed = date.today() - timedelta(days=2)
            session.add_all([
                CalibrationRecord(
                    id="cal-older", asset_id=active.id, certificate_number="CERT-OLD",
                    performed_at=performed, due_at=date.today() + timedelta(days=90),
                    performed_by="Lab", result="pass", recorded_by_id=None,
                    created_at=datetime(2026, 7, 30, 8, tzinfo=timezone.utc),
                ),
                CalibrationRecord(
                    id="cal-newer", asset_id=active.id, certificate_number="CERT-NEW",
                    performed_at=performed, due_at=date.today() + timedelta(days=120),
                    performed_by="Lab", result="fail", recorded_by_id=None,
                    created_at=datetime(2026, 7, 30, 9, tzinfo=timezone.utc),
                ),
            ])
            await session.commit()

            overview = await TransferService(session).get_equipment_transfer_overview()

            self.assertEqual(len(overview["items"]), 1)
            self.assertEqual(overview["items"][0]["asset_id"], active.id)
            self.assertEqual(overview["items"][0]["calibration_result"], "fail")
            self.assertFalse(overview["items"][0]["can_transfer"])

    async def test_out_of_service_equipment_is_blocked(self):
        async with self.sessions() as session:
            category_type = CategoryType(
                id="equipment-type", key="equipment", name="Equipment",
                stock_behavior="serialized", is_active=True,
            )
            category = Category(
                id="equipment-category", name="Equipment",
                category_type_id=category_type.id,
                stock_behavior="serialized", is_active=True,
            )
            item = Item(
                id="equipment-item", sku="EQ", name="Equipment",
                category_id=category.id, asset_type="equipment",
                is_serialized=True, requires_calibration=False, is_active=True,
            )
            location = Location(id="loc-1", code="LOC", name="Location", is_active=True)
            asset = SerializedAsset(
                id="asset-oos", item_id=item.id, serial_number="SER-OOS",
                location_id=location.id, acquired_at=date(2026, 1, 1),
                status=AssetStatus.OUT_OF_SERVICE,
            )
            session.add_all([category_type, category, item, location, asset])
            await session.commit()

            overview = await TransferService(session).get_equipment_transfer_overview()

            self.assertFalse(overview["items"][0]["can_transfer"])
            self.assertIn("Equipment is out of service", overview["items"][0]["blocked_reasons"])
