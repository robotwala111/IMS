"""Safe, audited permanent deletion for master data."""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete as sql_delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.db.base import Base
from app.models.audit import AuditLog
from app.models.asset import SerializedAsset
from app.models.calibration import CalibrationRecord, CalibrationSupplierTransaction
from app.models.category import Category
from app.models.item import ItemAttribute
from app.models.maintenance import MaintenanceRecord
from app.models.purchase_indent import PurchaseIndentItem
from app.models.item import Item
from app.models.location import Location
from app.models.stock import Stock, StockLot
from app.models.transaction import Transaction
from app.models.transfer import TransferItem
from app.models.user import User, user_location_association


class PermanentDeleteService:
    """Delete only unreferenced records and preserve an audit tombstone."""

    MODELS = {
        "item": Item,
        "stock": Stock,
        "location": Location,
        "user": User,
        "asset": SerializedAsset,
        "category": Category,
    }

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, entity: str, record_id: str) -> Any:
        model = self.MODELS[entity]
        result = await self.db.execute(select(model).where(model.id == record_id))
        record = result.scalar_one_or_none()
        if not record:
            raise NotFoundError(resource=entity.title(), resource_id=record_id)
        return record

    async def blockers(self, entity: str, record: Any) -> dict[str, int]:
        """Find every FK reference, including association and history tables."""
        target_table = self.MODELS[entity].__table__
        blockers: dict[str, int] = {}
        for table in Base.metadata.sorted_tables:
            for foreign_key in table.foreign_keys:
                if foreign_key.column.table is not target_table:
                    continue
                # Location assignments are configuration, not business history.
                # They are detached atomically immediately before deletion.
                if table is user_location_association:
                    continue
                query = select(func.count()).select_from(table).where(
                    foreign_key.parent == record.id
                )
                count = (await self.db.execute(query)).scalar_one()
                if count:
                    blockers[table.name] = blockers.get(table.name, 0) + count

        # A stock level is a business coordinate. History references its item and
        # location rather than stock.id, so check the coordinate explicitly.
        if entity == "stock":
            coordinate_checks = {
                "transactions": select(func.count(Transaction.id)).where(
                    Transaction.item_id == record.item_id,
                    Transaction.location_id == record.location_id,
                ),
                "stock_lots": select(func.count(StockLot.id)).where(
                    StockLot.item_id == record.item_id,
                    StockLot.location_id == record.location_id,
                ),
                "serialized_assets": select(func.count(SerializedAsset.id)).where(
                    SerializedAsset.item_id == record.item_id,
                    SerializedAsset.location_id == record.location_id,
                ),
            }
            for label, query in coordinate_checks.items():
                count = (await self.db.execute(query)).scalar_one()
                if count:
                    blockers[label] = count

            quantities = (
                record.quantity_on_hand,
                record.quantity_reserved,
                record.quantity_on_order,
            )
            if any(quantities):
                blockers["non-zero quantities"] = 1

        return blockers

    async def delete(
        self,
        entity: str,
        record_id: str,
        admin: User,
        force_stock_balance: bool = False,
        force_category_items: bool = False,
        force_user_dependencies: bool = False,
    ) -> str:
        record = await self.get(entity, record_id)
        if entity == "user" and force_user_dependencies:
            await self._remove_user_dependencies(record_id)
        blockers = await self.blockers(entity, record)
        category_item_ids: list[str] = []
        if entity == "category" and force_category_items:
            category_item_ids = list((await self.db.execute(
                select(Item.id).where(Item.category_id == record_id)
            )).scalars().all())
            blockers.pop("items", None)
        if entity == "stock" and force_stock_balance:
            # Stock transactions are retained history and reference the item /
            # location coordinate, not the balance row. An Admin may explicitly
            # discard only the current balance after seeing the impact warning.
            blockers.pop("transactions", None)
            blockers.pop("non-zero quantities", None)
        if blockers:
            if entity == "stock":
                history_count = blockers.get("transactions", 0)
                balance_present = "non-zero quantities" in blockers
                impact = (
                    f"Current balance: {record.quantity_on_hand} on hand "
                    f"({record.quantity_reserved} reserved), "
                    f"{record.quantity_on_order} on order; "
                    f"transaction history records retained: {history_count}. "
                    if balance_present or history_count else ""
                )
            else:
                impact = ""
            details = ", ".join(f"{count} {name}" for name, count in blockers.items())
            raise ConflictError(
                message=f"Cannot permanently delete {entity}; {impact}referenced by {details}."
            )

        name = (
            getattr(record, "name", None)
            or getattr(record, "email", None)
            or getattr(record, "sku", None)
            or record_id
        )
        snapshot = {
            column.name: str(getattr(record, column.name))
            if getattr(record, column.name) is not None
            else None
            for column in record.__table__.columns
        }
        if category_item_ids:
            snapshot["forced_related_items_deleted"] = len(category_item_ids)
        audit = AuditLog(
            id=str(uuid4()),
            action="permanent_delete",
            resource_type=entity,
            resource_id=record_id,
            resource_name=str(name),
            user_id=admin.id,
            user_email=admin.email,
            user_name=admin.name,
            user_role=admin.role.value,
            old_value=json.dumps(snapshot),
            new_value=None,
            status="success",
            occurred_at=datetime.now(timezone.utc),
        )

        try:
            if category_item_ids:
                asset_ids = list((await self.db.execute(
                    select(SerializedAsset.id).where(
                        SerializedAsset.item_id.in_(category_item_ids)
                    )
                )).scalars().all())
                if asset_ids:
                    await self.db.execute(sql_delete(Transaction).where(Transaction.asset_id.in_(asset_ids)))
                    await self.db.execute(sql_delete(CalibrationSupplierTransaction).where(CalibrationSupplierTransaction.asset_id.in_(asset_ids)))
                    await self.db.execute(sql_delete(CalibrationRecord).where(CalibrationRecord.asset_id.in_(asset_ids)))
                    await self.db.execute(sql_delete(MaintenanceRecord).where(MaintenanceRecord.asset_id.in_(asset_ids)))
                await self.db.execute(sql_delete(Transaction).where(Transaction.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(TransferItem).where(TransferItem.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(PurchaseIndentItem).where(PurchaseIndentItem.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(StockLot).where(StockLot.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(Stock).where(Stock.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(SerializedAsset).where(SerializedAsset.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(ItemAttribute).where(ItemAttribute.item_id.in_(category_item_ids)))
                await self.db.execute(sql_delete(Item).where(Item.id.in_(category_item_ids)))
            if entity == "user":
                await self.db.execute(
                    sql_delete(user_location_association).where(
                        user_location_association.c.user_id == record_id
                    )
                )
            elif entity == "location":
                await self.db.execute(
                    sql_delete(user_location_association).where(
                        user_location_association.c.location_id == record_id
                    )
                )
            # Use a Core DELETE after exhaustive FK checks. ORM deletion would
            # traverse configured delete cascades and can load/delete children,
            # which is explicitly forbidden for business history.
            await self.db.execute(
                sql_delete(self.MODELS[entity]).where(
                    self.MODELS[entity].id == record_id
                )
            )
            self.db.add(audit)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError(
                message=f"Cannot permanently delete {entity}; it is still referenced."
            ) from exc
        return str(name)

    async def _remove_user_dependencies(self, user_id: str) -> None:
        """Delete owned records and detach nullable user attribution."""
        from app.models.purchase_indent import PurchaseIndent
        from app.models.transfer import Transfer

        # Purchase indents owned by the user require their linked transfers to
        # be removed first because Transfer.purchase_indent_id is restrictive.
        indent_ids = list((await self.db.execute(
            select(PurchaseIndent.id).where(PurchaseIndent.requested_by_id == user_id)
        )).scalars().all())
        owned_transfer_condition = Transfer.requested_by_id == user_id
        if indent_ids:
            owned_transfer_condition = or_(
                owned_transfer_condition,
                Transfer.purchase_indent_id.in_(indent_ids),
            )
        transfer_ids = list((await self.db.execute(
            select(Transfer.id).where(owned_transfer_condition)
        )).scalars().all())
        if transfer_ids:
            await self.db.execute(sql_delete(TransferItem).where(TransferItem.transfer_id.in_(transfer_ids)))
            await self.db.execute(sql_delete(Transfer).where(Transfer.id.in_(transfer_ids)))
        if indent_ids:
            await self.db.execute(sql_delete(PurchaseIndentItem).where(PurchaseIndentItem.indent_id.in_(indent_ids)))
            await self.db.execute(sql_delete(PurchaseIndent).where(PurchaseIndent.id.in_(indent_ids)))

        # For all remaining direct user FKs: non-nullable means the record is
        # owned by the user and is deleted; nullable attribution is detached.
        skipped = {"users", "user_locations", "transfers", "purchase_indents"}
        for table in Base.metadata.sorted_tables:
            if table.name in skipped:
                continue
            user_fk_columns = [
                fk.parent for fk in table.foreign_keys
                if fk.column.table is User.__table__
            ]
            if not user_fk_columns:
                continue
            required = [column for column in user_fk_columns if not column.nullable]
            optional = [column for column in user_fk_columns if column.nullable]
            if required:
                await self.db.execute(
                    table.delete().where(or_(*(column == user_id for column in required)))
                )
            for column in optional:
                await self.db.execute(
                    update(table).where(column == user_id).values({column.name: None})
                )

        # Transfers/PIs where the user was only an approver/handler are kept.
        for table in (Transfer.__table__, PurchaseIndent.__table__):
            for foreign_key in table.foreign_keys:
                column = foreign_key.parent
                if foreign_key.column.table is User.__table__ and column.nullable:
                    await self.db.execute(
                        update(table).where(column == user_id).values({column.name: None})
                    )
