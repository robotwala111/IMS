"""One-time destructive cleanup of all transfers and purchase indents."""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select

from app.db.session import async_session_factory
from app.models.audit import AuditLog
from app.models.purchase_indent import PurchaseIndent, PurchaseIndentItem
from app.models.transfer import Transfer, TransferItem

CONFIRMATION = "DELETE_ALL_TRANSFERS_AND_PURCHASE_INDENTS"


async def cleanup(dry_run: bool = False) -> None:
    async with async_session_factory() as session:
        models = [TransferItem, Transfer, PurchaseIndentItem, PurchaseIndent]
        before = {}
        for model in models:
            before[model.__tablename__] = (
                await session.execute(select(func.count()).select_from(model))
            ).scalar_one()

        if dry_run:
            print(json.dumps({"would_delete": before}, indent=2))
            return

        try:
            deleted = {}
            for model in models:
                result = await session.execute(delete(model))
                deleted[model.__tablename__] = result.rowcount or 0
            session.add(AuditLog(
                id=str(uuid4()), action="one_time_dummy_data_cleanup",
                resource_type="transfer_and_purchase_indent", resource_id=None,
                resource_name="All transfers and purchase indents",
                user_name="System cleanup", user_role="admin", status="success",
                old_value=json.dumps(before), new_value=json.dumps(deleted),
                occurred_at=datetime.now(timezone.utc),
            ))
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        print(json.dumps({"before": before, "deleted": deleted}, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        asyncio.run(cleanup(dry_run=True))
        return
    if args.confirm != CONFIRMATION:
        raise SystemExit(f"Refusing cleanup; --confirm must equal {CONFIRMATION}")
    asyncio.run(cleanup())


if __name__ == "__main__":
    main()
