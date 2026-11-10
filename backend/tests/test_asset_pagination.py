"""Regression tests for Products pagination."""

import unittest
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.asset import SerializedAsset
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.models.location import Location
from app.services.asset_service import AssetService
from app.core.exceptions import BadRequestError


class AssetPaginationTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_all_assets_are_reachable_when_timestamps_match(self):
        async with self.sessions() as session:
            category_type = CategoryType(
                id="type-equipment", key="equipment", name="Equipment",
                stock_behavior="serialized", is_active=True,
            )
            category = Category(
                id="category-equipment", name="Equipment",
                category_type_id=category_type.id, stock_behavior="serialized",
                is_active=True,
            )
            item = Item(
                id="item-equipment", sku="EQ-MASTER", name="Equipment",
                category_id=category.id, asset_type="equipment",
                is_serialized=True, unit_of_measure="EA", is_active=True,
            )
            location = Location(
                id="location-main", code="MAIN", name="Main", is_active=True,
            )
            session.add_all([category_type, category, item, location])
            await session.flush()

            created_at = datetime(2026, 7, 30, tzinfo=timezone.utc)
            session.add_all([
                SerializedAsset(
                    id=f"asset-{index:03}", item_id=item.id,
                    serial_number=f"SERIAL-{index:03}",
                    location_id=location.id, acquired_at=date(2026, 7, 30),
                    created_at=created_at, updated_at=created_at,
                )
                for index in range(125)
            ])
            await session.commit()

            first, total = await AssetService(session).list_assets(
                page=1, page_size=100, sort_by="created_at", sort_order="desc",
            )
            second, _ = await AssetService(session).list_assets(
                page=2, page_size=100, sort_by="created_at", sort_order="desc",
            )

            ids = {asset.id for asset in first + second}
            self.assertEqual(total, 125)
            self.assertEqual(len(first), 100)
            self.assertEqual(len(second), 25)
            self.assertEqual(len(ids), 125)

    async def test_serial_number_can_be_changed_but_not_duplicated(self):
        async with self.sessions() as session:
            category_type = CategoryType(
                id="type-equipment", key="equipment", name="Equipment",
                stock_behavior="serialized", is_active=True,
            )
            category = Category(
                id="category-equipment", name="Equipment",
                category_type_id=category_type.id, stock_behavior="serialized",
                is_active=True,
            )
            item = Item(
                id="item-equipment", sku="EQ-MASTER", name="Equipment",
                category_id=category.id, asset_type="equipment",
                is_serialized=True, unit_of_measure="EA", is_active=True,
            )
            location = Location(
                id="location-main", code="MAIN", name="Main", is_active=True,
            )
            session.add_all([category_type, category, item, location])
            await session.flush()
            session.add_all([
                SerializedAsset(
                    id="asset-one", item_id=item.id, serial_number="SERIAL-ONE",
                    location_id=location.id, acquired_at=date(2026, 7, 30),
                ),
                SerializedAsset(
                    id="asset-two", item_id=item.id, serial_number="SERIAL-TWO",
                    location_id=location.id, acquired_at=date(2026, 7, 30),
                ),
            ])
            await session.commit()

            service = AssetService(session)
            updated = await service.update_asset("asset-one", serial_number="SERIAL-NEW")
            self.assertEqual(updated.serial_number, "SERIAL-NEW")

            with self.assertRaises(BadRequestError):
                await service.update_asset("asset-one", serial_number="SERIAL-TWO")
