"""Focused safety tests for permanent deletion."""

import unittest
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.exceptions import ConflictError
from app.db.base import Base
from app.models.audit import AuditLog
from app.models.category import Category
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock
from app.models.transaction import Transaction, TransactionType
from app.models.user import User, UserRole
from app.services.permanent_delete_service import PermanentDeleteService


class PermanentDeleteServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_master_data(self, session):
        admin = User(
            id="admin-1", email="admin@example.com", name="Admin",
            password_hash="hash", role=UserRole.ADMIN, is_active=True,
        )
        location = Location(id="loc-1", code="LOC", name="Location", is_active=True)
        category = Category(id="cat-1", name="Consumable", is_active=True)
        item = Item(
            id="item-1", sku="SKU-1", name="Product", category_id=category.id,
            unit_of_measure="EA", is_active=True,
        )
        session.add_all([admin, location, category, item])
        await session.commit()
        return admin, location, item

    async def test_unreferenced_item_is_deleted_with_success_audit(self):
        async with self.sessions() as session:
            admin, _, item = await self._seed_master_data(session)
            await PermanentDeleteService(session).delete("item", item.id, admin)

            self.assertIsNone(await session.get(Item, item.id))
            audit = (await session.execute(
                select(AuditLog).where(AuditLog.resource_id == item.id)
            )).scalar_one()
            self.assertEqual(audit.action, "permanent_delete")
            self.assertEqual(audit.status, "success")
            self.assertEqual(audit.user_id, admin.id)

    async def test_business_history_blocks_stock_deletion(self):
        async with self.sessions() as session:
            admin, location, item = await self._seed_master_data(session)
            stock = Stock(id="stock-1", item_id=item.id, location_id=location.id)
            transaction = Transaction(
                id="tx-1", transaction_type=TransactionType.RECEIPT,
                item_id=item.id, location_id=location.id, quantity=1,
                created_by_id=admin.id, transaction_date=datetime.now(timezone.utc),
            )
            session.add_all([stock, transaction])
            await session.commit()

            with self.assertRaises(ConflictError) as caught:
                await PermanentDeleteService(session).delete("stock", stock.id, admin)
            self.assertIn("transactions", caught.exception.message)
            self.assertIsNotNone(await session.get(Stock, stock.id))

    async def test_admin_can_force_delete_balance_but_history_is_retained(self):
        async with self.sessions() as session:
            admin, location, item = await self._seed_master_data(session)
            stock = Stock(
                id="stock-force", item_id=item.id, location_id=location.id,
                quantity_on_hand=12, quantity_reserved=2,
            )
            transaction = Transaction(
                id="tx-force", transaction_type=TransactionType.RECEIPT,
                item_id=item.id, location_id=location.id, quantity=12,
                created_by_id=admin.id, transaction_date=datetime.now(timezone.utc),
            )
            session.add_all([stock, transaction])
            await session.commit()

            await PermanentDeleteService(session).delete(
                "stock", stock.id, admin, force_stock_balance=True
            )

            self.assertIsNone(await session.get(Stock, stock.id))
            self.assertIsNotNone(await session.get(Transaction, transaction.id))

    async def test_user_location_assignments_are_detached_not_blocked(self):
        async with self.sessions() as session:
            admin, location, _ = await self._seed_master_data(session)
            target = User(
                id="user-2", email="manager@example.com", name="Manager",
                password_hash="hash", role=UserRole.LOCATION_MANAGER, is_active=False,
                assigned_locations=[location],
            )
            session.add(target)
            await session.commit()

            await PermanentDeleteService(session).delete("user", target.id, admin)

            self.assertIsNone(await session.get(User, target.id))
            audit_count = (await session.execute(
                select(func.count(AuditLog.id)).where(
                    AuditLog.resource_id == target.id,
                    AuditLog.action == "permanent_delete",
                )
            )).scalar_one()
            self.assertEqual(audit_count, 1)

    async def test_admin_can_force_delete_category_and_linked_items(self):
        async with self.sessions() as session:
            admin, _, item = await self._seed_master_data(session)
            category_id = item.category_id

            await PermanentDeleteService(session).delete(
                "category", category_id, admin, force_category_items=True
            )

            self.assertIsNone(await session.get(Item, item.id))
            self.assertIsNone(await session.get(Category, category_id))

    async def test_admin_can_force_delete_user_owned_history(self):
        async with self.sessions() as session:
            admin, location, item = await self._seed_master_data(session)
            target = User(
                id="user-force", email="force@example.com", name="Force User",
                password_hash="hash", role=UserRole.LOCATION_MANAGER, is_active=False,
            )
            transaction = Transaction(
                id="tx-user-force", transaction_type=TransactionType.RECEIPT,
                item_id=item.id, location_id=location.id, quantity=1,
                created_by_id=target.id, transaction_date=datetime.now(timezone.utc),
            )
            session.add_all([target, transaction])
            await session.commit()

            await PermanentDeleteService(session).delete(
                "user", target.id, admin, force_user_dependencies=True
            )

            self.assertIsNone(await session.get(User, target.id))
            remaining = (await session.execute(
                select(func.count(Transaction.id)).where(Transaction.id == transaction.id)
            )).scalar_one()
            self.assertEqual(remaining, 0)


if __name__ == "__main__":
    unittest.main()
