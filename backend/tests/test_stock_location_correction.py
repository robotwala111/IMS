"""Tests for correcting a quantity-based stock item's location."""

import unittest
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock, StockLot
from app.models.transaction import Transaction, TransactionType
from app.models.user import User, UserRole
from app.services.stock_service import StockService


class StockLocationCorrectionTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed(self, session):
        admin = User(
            id="admin-location", email="location@example.com", name="Admin",
            password_hash="hash", role=UserRole.ADMIN, is_active=True,
        )
        source = Location(id="loc-source", code="SRC", name="Source", is_active=True)
        destination = Location(id="loc-destination", code="DST", name="Destination", is_active=True)
        category = Category(id="cat-stock", name="Consumables", is_active=True)
        item = Item(
            id="item-stock", sku="SKU-STOCK", name="Stock Item",
            category_id=category.id, unit_of_measure="EA", is_active=True,
        )
        session.add_all([admin, source, destination, category, item])
        await session.commit()
        return admin, item

    async def test_moves_balance_lots_and_records_history(self):
        async with self.sessions() as session:
            admin, item = await self._seed(session)
            stock = Stock(
                id="stock-source", item_id=item.id, location_id="loc-source",
                quantity_on_hand=23, quantity_reserved=3, quantity_on_order=4,
            )
            lot = StockLot(
                id="lot-source", item_id=item.id, location_id="loc-source",
                lot_number="LOT-1", quantity_on_hand=23, quantity_reserved=3,
                received_at=datetime.now(timezone.utc),
            )
            session.add_all([stock, lot])
            await session.commit()

            result = await StockService(session).correct_location(
                stock.id, "loc-destination", admin.id, "Wrong location selected",
            )

            await session.refresh(stock)
            await session.refresh(lot)
            self.assertEqual(stock.location_id, "loc-destination")
            self.assertEqual(stock.quantity_on_hand, 23)
            self.assertEqual(stock.quantity_reserved, 3)
            self.assertEqual(stock.quantity_on_order, 4)
            self.assertEqual(lot.location_id, "loc-destination")
            self.assertFalse(result["merged"])

            transactions = list((await session.execute(
                select(Transaction).order_by(Transaction.transaction_type)
            )).scalars())
            self.assertEqual(len(transactions), 2)
            self.assertEqual(
                {transaction.transaction_type for transaction in transactions},
                {TransactionType.TRANSFER_OUT, TransactionType.TRANSFER_IN},
            )
            self.assertTrue(all(transaction.quantity == 23 for transaction in transactions))

    async def test_merges_with_existing_destination_without_changing_total(self):
        async with self.sessions() as session:
            admin, item = await self._seed(session)
            source = Stock(
                id="stock-source", item_id=item.id, location_id="loc-source",
                quantity_on_hand=10, quantity_reserved=2, quantity_on_order=1,
            )
            destination = Stock(
                id="stock-destination", item_id=item.id, location_id="loc-destination",
                quantity_on_hand=7, quantity_reserved=1, quantity_on_order=3,
            )
            session.add_all([source, destination])
            await session.commit()

            result = await StockService(session).correct_location(
                source.id, "loc-destination", admin.id, "Wrong location selected",
            )

            await session.refresh(source)
            await session.refresh(destination)
            self.assertFalse(source.is_active)
            self.assertEqual(source.quantity_on_hand, 0)
            self.assertEqual(destination.quantity_on_hand, 17)
            self.assertEqual(destination.quantity_reserved, 3)
            self.assertEqual(destination.quantity_on_order, 4)
            self.assertTrue(result["merged"])
            self.assertEqual(result["stock_id"], destination.id)
