"""Replace inventory-related records with a synthetic Amiro demo dataset.

Run from backend/: python scripts/replace_synthetic_inventory.py --yes
A timestamped SQLite copy is saved before the replacement.
Locations, user accounts, and unrelated modules are preserved.
"""

import argparse
import asyncio
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.db.session import async_session_factory, database_url, engine, init_db
from app.core.logging import get_logger

logger = get_logger(__name__)

# Child tables are cleared before their parents to keep foreign keys valid.
DELETE_ORDER = (
    "transfer_items",
    "transfers",
    "purchase_indent_items",
    "purchase_indents",
    "transactions",
    "calibration_supplier_transactions",
    "calibration_records",
    "maintenance_records",
    "serialized_assets",
    "stock_lots",
    "stocks",
    "item_attributes",
    "items",
    "categories",
)


def backup_sqlite_database() -> Path | None:
    if not settings.is_sqlite:
        return None
    db_path = Path(make_url(database_url).database or "")
    if not db_path.is_absolute():
        db_path = (Path(__file__).resolve().parents[1] / db_path).resolve()
    if not db_path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = db_path.with_name(f"{db_path.stem}.before_synthetic_{stamp}{db_path.suffix}")
    with sqlite3.connect(db_path) as source, sqlite3.connect(backup_path) as destination:
        source.backup(destination)
    return backup_path


async def clear_inventory_data() -> None:
    async with engine.begin() as conn:
        tables = set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))
        for table in DELETE_ORDER:
            if table in tables:
                await conn.execute(text(f'DELETE FROM "{table}"'))


async def main() -> None:
    parser = argparse.ArgumentParser(description="Replace inventory demo data with synthetic records.")
    parser.add_argument("--yes", action="store_true", help="confirm replacement of inventory demo records")
    args = parser.parse_args()
    if not args.yes:
        parser.error("This resets products, categories, stock, transfers, transactions, and compliance records. Re-run with --yes to confirm.")
    if not settings.is_sqlite:
        parser.error("For safety, this script only resets the local SQLite demo database.")

    backup = backup_sqlite_database()
    if backup:
        logger.info("Saved pre-replacement database copy: %s", backup)

    await init_db()
    await clear_inventory_data()

    # Rebuild inventory using the same repeatable domain seed routines as the app.
    from scripts.seed_data import run_seed
    from scripts.add_sample_data import run_add_data

    await run_seed()
    await run_add_data()
    logger.info("Synthetic products, stock, categories, transfers, and compliance data are ready.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
