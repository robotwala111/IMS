"""
Add Sample Data Script

Creates focused sample data for ScienceTech-IMS demo/testing:

  Transactions : 6  (2 receipt, 2 issue, 1 return, 1 adjustment)
  Transfers    : 7  (mix of consumable + equipment, all statuses covered)
                    - Equipment transfers include return_date + return_reminder_days
                    - Each transfer is linked to an auto-created Purchase Indent (PI)
                    - Delivery Challan (DC) can be printed for approved/in-transit/received transfers
  Assets       : 5  (1-2 per serialized item)
  Calibration  : 5  (1 per asset)
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.session import async_session_factory, init_db
from app.models.location import Location
from app.models.item import Item
from app.models.stock import Stock
from app.models.transaction import Transaction, TransactionType
from app.models.transfer import Transfer, TransferStatus, TransferItem
from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus, PurchaseIndentItem
from app.models.user import User
from app.models.asset import SerializedAsset, AssetStatus
from app.models.calibration import CalibrationRecord
from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

async def add_transactions(db, locations, items, users):
    existing = await db.execute(select(Transaction.id).limit(1))
    if existing.scalar_one_or_none() is not None:
        logger.info("Transactions already exist, skipping")
        return 0

    now = datetime.now(timezone.utc)
    blr = locations[0]
    mng = locations[1] if len(locations) > 1 else locations[0]
    admin = users[0]

    # Pick consumable items for transactions
    consumables = [i for i in items if not i.is_serialized]
    if len(consumables) < 2:
        consumables = items

    txns = [
        # Receipts
        Transaction(
            id=str(uuid.uuid4()), transaction_type=TransactionType.RECEIPT,
            item_id=consumables[0].id, location_id=blr.id,
            quantity=20, unit_cost=float(consumables[0].standard_cost or 350),
            total_cost=20 * float(consumables[0].standard_cost or 350),
            reference_number="TXN-2026-0001",
            reason="Received from vendor — monthly restocking",
            created_by_id=admin.id, transaction_date=now - timedelta(days=5),
        ),
        Transaction(
            id=str(uuid.uuid4()), transaction_type=TransactionType.RECEIPT,
            item_id=consumables[1].id if len(consumables) > 1 else consumables[0].id,
            location_id=mng.id,
            quantity=12, unit_cost=float((consumables[1] if len(consumables) > 1 else consumables[0]).standard_cost or 950),
            total_cost=12 * float((consumables[1] if len(consumables) > 1 else consumables[0]).standard_cost or 950),
            reference_number="TXN-2026-0002",
            reason="Purchase order delivery",
            created_by_id=admin.id, transaction_date=now - timedelta(days=4),
        ),
        # Issues
        Transaction(
            id=str(uuid.uuid4()), transaction_type=TransactionType.ISSUE,
            item_id=consumables[0].id, location_id=blr.id,
            quantity=-5, unit_cost=float(consumables[0].standard_cost or 350),
            total_cost=5 * float(consumables[0].standard_cost or 350),
            reference_number="TXN-2026-0003",
            reason="Issued to field team — Tata Steel inspection",
            created_by_id=admin.id, transaction_date=now - timedelta(days=3),
        ),
        Transaction(
            id=str(uuid.uuid4()), transaction_type=TransactionType.ISSUE,
            item_id=consumables[1].id if len(consumables) > 1 else consumables[0].id,
            location_id=mng.id,
            quantity=-3, unit_cost=float((consumables[1] if len(consumables) > 1 else consumables[0]).standard_cost or 950),
            total_cost=3 * float((consumables[1] if len(consumables) > 1 else consumables[0]).standard_cost or 950),
            reference_number="TXN-2026-0004",
            reason="Issued for BHEL Trichy PT inspection",
            created_by_id=admin.id, transaction_date=now - timedelta(days=2),
        ),
        # Return
        Transaction(
            id=str(uuid.uuid4()), transaction_type=TransactionType.RETURN,
            item_id=consumables[0].id, location_id=blr.id,
            quantity=2, unit_cost=float(consumables[0].standard_cost or 350),
            total_cost=2 * float(consumables[0].standard_cost or 350),
            reference_number="TXN-2026-0005",
            reason="Returned unused material from site",
            created_by_id=admin.id, transaction_date=now - timedelta(days=1),
        ),
        # Adjustment
        Transaction(
            id=str(uuid.uuid4()), transaction_type=TransactionType.ADJUSTMENT,
            item_id=consumables[0].id, location_id=blr.id,
            quantity=-1, unit_cost=float(consumables[0].standard_cost or 350),
            total_cost=float(consumables[0].standard_cost or 350),
            reference_number="TXN-2026-0006",
            reason="Inventory count correction — damaged item write-off",
            created_by_id=admin.id, transaction_date=now,
        ),
    ]

    for txn in txns:
        db.add(txn)

    await db.commit()
    logger.info(f"Added {len(txns)} transactions")
    return len(txns)


# ---------------------------------------------------------------------------
# Purchase Indents + Transfers
#
# Business flow:
#   1. Transfer is requested  PI is auto-created (SUBMITTED)
#   2. Supplying location manager reviews & approves PI  PI becomes APPROVED
#   3. Transfer is approved / shipped / received
#
# The DC (Delivery Challan) button in the UI is enabled for transfers with
# status: approved, in_transit, received.
# ---------------------------------------------------------------------------

async def add_transfers_with_pi(db, locations, items, users):
    existing = await db.execute(select(Transfer.id).limit(1))
    if existing.scalar_one_or_none() is not None:
        logger.info("Transfers already exist, skipping")
        return 0

    if len(locations) < 2:
        logger.warning("Need at least 2 locations for transfers, skipping")
        return 0

    blr  = locations[0]   # Bangalore Head Office — supplying location
    mng  = locations[1]   # Mangalore Branch — requesting location
    hyd  = locations[2] if len(locations) > 2 else locations[1]
    admin    = users[0]
    manager  = users[1] if len(users) > 1 else users[0]

    sku_map = {i.sku: i for i in items}
    cons_items  = [i for i in items if not i.is_serialized]
    equip_items = [i for i in items if i.is_serialized]

    now = datetime.now(timezone.utc)

    # -----------------------------------------------------------------------
    # scenario helper
    # -----------------------------------------------------------------------
    created = 0

    async def make_transfer(
        number, pi_number, from_loc, to_loc, status,
        transfer_items,   # list of (Item, qty)
        days_ago, transfer_type,
        return_date=None, return_reminder_days=None,
        notes="",
        pi_status=None,
    ):
        nonlocal created
        requested_date = now - timedelta(days=days_ago)
        is_equipment    = transfer_type == "equipment"

        # --- PI ---
        pi_id = str(uuid.uuid4())
        pi_st = pi_status or (
            PurchaseIndentStatus.FULFILLED if status == TransferStatus.RECEIVED
            else PurchaseIndentStatus.APPROVED if status in (TransferStatus.IN_TRANSIT, TransferStatus.APPROVED)
            else PurchaseIndentStatus.SUBMITTED
        )
        pi = PurchaseIndent(
            id=pi_id,
            indent_number=pi_number,
            requested_by_location_id=to_loc.id,
            supplying_location_id=from_loc.id,
            requested_by_id=admin.id,
            approved_by_id=manager.id if pi_st in (PurchaseIndentStatus.APPROVED, PurchaseIndentStatus.FULFILLED) else None,
            status=pi_st,
            indent_date=requested_date,
            required_by_date=requested_date + timedelta(days=3),
            approved_at=requested_date + timedelta(hours=4) if pi_st in (PurchaseIndentStatus.APPROVED, PurchaseIndentStatus.FULFILLED) else None,
            purpose=f"Auto-raised for transfer {number}",
            notes=notes,
        )
        db.add(pi)
        await db.flush()

        # PI line items
        for item, qty in transfer_items:
            db.add(PurchaseIndentItem(
                id=str(uuid.uuid4()),
                indent_id=pi_id,
                item_id=item.id,
                quantity_requested=qty,
                quantity_approved=qty if pi_st in (PurchaseIndentStatus.APPROVED, PurchaseIndentStatus.FULFILLED) else None,
            ))

        # --- Transfer ---
        trf_id = str(uuid.uuid4())
        trf = Transfer(
            id=trf_id,
            transfer_number=number,
            transfer_type=transfer_type,
            from_location_id=from_loc.id,
            to_location_id=to_loc.id,
            status=status,
            priority="high" if is_equipment else "normal",
            requested_date=requested_date,
            required_by_date=requested_date + timedelta(days=3),
            requested_by_id=admin.id,
            approved_by_id=manager.id if status not in (TransferStatus.REQUESTED,) else None,
            approved_at=requested_date + timedelta(hours=5) if status not in (TransferStatus.REQUESTED,) else None,
            shipped_at=requested_date + timedelta(hours=8) if status in (TransferStatus.IN_TRANSIT, TransferStatus.RECEIVED) else None,
            received_at=requested_date + timedelta(days=1) if status == TransferStatus.RECEIVED else None,
            request_notes=notes,
            purchase_indent_id=pi_id,
            # Equipment-specific: return date for tracking
            return_date=(now + timedelta(days=return_date)).date() if return_date else None,
            return_reminder_days=return_reminder_days,
        )
        db.add(trf)
        await db.flush()

        # Transfer line items
        for item, qty in transfer_items:
            shipped = qty if status in (TransferStatus.IN_TRANSIT, TransferStatus.RECEIVED) else None
            received = qty if status == TransferStatus.RECEIVED else None
            db.add(TransferItem(
                id=str(uuid.uuid4()),
                transfer_id=trf_id,
                item_id=item.id,
                quantity_requested=qty,
                quantity_shipped=shipped,
                quantity_received=received,
            ))

        created += 1

    # -----------------------------------------------------------------------
    # Consumable transfers
    # -----------------------------------------------------------------------
    couplant = sku_map.get("UT-COUPLANT-500") or (cons_items[0] if cons_items else None)
    penetrant = sku_map.get("PT-ZL27A") or (cons_items[1] if len(cons_items) > 1 else None)
    ipa = sku_map.get("CON-IPA-1L") or (cons_items[2] if len(cons_items) > 2 else None)

    if couplant:
        await make_transfer(
            "TRF-2026-001", "PI-2026-001",
            from_loc=blr, to_loc=mng,
            status=TransferStatus.REQUESTED,
            transfer_items=[(couplant, 8)],
            days_ago=1, transfer_type="consumable",
            notes="Couplant gel for upcoming weld inspection campaign",
        )

    if penetrant and ipa:
        await make_transfer(
            "TRF-2026-002", "PI-2026-002",
            from_loc=blr, to_loc=mng,
            status=TransferStatus.APPROVED,
            transfer_items=[(penetrant, 6), (ipa, 10)],
            days_ago=3, transfer_type="consumable",
            notes="PT consumables restocking — BHEL Trichy project",
        )

    if couplant and ipa:
        await make_transfer(
            "TRF-2026-003", "PI-2026-003",
            from_loc=mng, to_loc=hyd,
            status=TransferStatus.RECEIVED,
            transfer_items=[(couplant, 5), (ipa, 5)],
            days_ago=7, transfer_type="consumable",
            notes="Consumables sent to Hyderabad for pipeline job",
        )

    # -----------------------------------------------------------------------
    # Equipment transfers (serialized — RETURNABLE, with return dates)
    # -----------------------------------------------------------------------
    epoch = sku_map.get("UT-EPOCH650") or (equip_items[0] if equip_items else None)
    yoke  = sku_map.get("MPT-YOKE-ACDC") or (equip_items[1] if len(equip_items) > 1 else None)
    cal_block = sku_map.get("CAL-V1-BLOCK") or (equip_items[2] if len(equip_items) > 2 else None)

    if epoch:
        await make_transfer(
            "TRF-2026-004", "PI-2026-004",
            from_loc=blr, to_loc=mng,
            status=TransferStatus.REQUESTED,
            transfer_items=[(epoch, 1)],
            days_ago=1, transfer_type="equipment",
            return_date=30, return_reminder_days=5,
            notes="EPOCH 650 needed for shutdown UT inspection — return within 30 days",
        )

    if yoke:
        await make_transfer(
            "TRF-2026-005", "PI-2026-005",
            from_loc=blr, to_loc=hyd,
            status=TransferStatus.IN_TRANSIT,
            transfer_items=[(yoke, 1)],
            days_ago=2, transfer_type="equipment",
            return_date=14, return_reminder_days=3,
            notes="MPT yoke dispatched to Hyderabad — crane hook inspection",
        )

    if epoch and cal_block:
        await make_transfer(
            "TRF-2026-006", "PI-2026-006",
            from_loc=mng, to_loc=blr,
            status=TransferStatus.RECEIVED,
            transfer_items=[(epoch, 1), (cal_block, 1)],
            days_ago=10, transfer_type="equipment",
            notes="Equipment returned from Mangalore site inspection",
        )

    if yoke:
        await make_transfer(
            "TRF-2026-007", "PI-2026-007",
            from_loc=blr, to_loc=mng,
            status=TransferStatus.APPROVED,
            transfer_items=[(yoke, 1)],
            days_ago=4, transfer_type="equipment",
            return_date=21, return_reminder_days=3,
            notes="Approved — yoke for MPT corrosion survey at Mangalore port",
        )

    await db.commit()
    logger.info(f"Added {created} transfers with linked Purchase Indents")
    return created


# ---------------------------------------------------------------------------
# Serialized Assets
# ---------------------------------------------------------------------------

async def add_serialized_assets(db, locations, items, users):
    existing = await db.execute(select(SerializedAsset.id).limit(1))
    if existing.scalar_one_or_none() is not None:
        logger.info("Serialized assets already exist, skipping")
        return 0

    serialized_items = [i for i in items if i.is_serialized]
    if not serialized_items:
        return 0

    blr = locations[0]
    mng = locations[1] if len(locations) > 1 else locations[0]
    admin = users[0]

    now = datetime.now(timezone.utc)
    assets_created = 0

    for idx, item in enumerate(serialized_items):
        for unit in range(1, 3):   # 2 units per serialized item
            loc = blr if unit == 1 else mng
            serial = f"{item.sku}-{loc.code[:3]}-{unit:03d}"
            purchased = now - timedelta(days=200 + idx * 30)
            db.add(SerializedAsset(
                id=str(uuid.uuid4()),
                item_id=item.id,
                serial_number=serial,
                location_id=loc.id,
                status=AssetStatus.IN_SERVICE,
                acquired_at=purchased.date(),
                cost=float(item.standard_cost or 50000),
                warranty_expiry=(purchased + timedelta(days=365)).date(),
                notes=f"Demo asset for {item.name} at {loc.name}",
            ))
            assets_created += 1

    await db.commit()
    logger.info(f"Added {assets_created} serialized assets")
    return assets_created


# ---------------------------------------------------------------------------
# Calibration Records
# ---------------------------------------------------------------------------

async def add_calibration_records(db, users):
    existing = await db.execute(select(CalibrationRecord.id).limit(1))
    if existing.scalar_one_or_none() is not None:
        logger.info("Calibration records already exist, skipping")
        return 0

    from sqlalchemy.orm import selectinload

    assets_res = await db.execute(
        select(SerializedAsset).options(selectinload(SerializedAsset.item))
    )
    assets = [a for a in assets_res.scalars().all() if a.item and a.item.requires_calibration]

    if not assets:
        return 0

    admin = users[0]
    now = datetime.now(timezone.utc)
    cal_labs = [
        "NDT Calibration Services Pvt Ltd, Bangalore",
        "Internal Calibration Lab",
    ]

    count = 0
    for idx, asset in enumerate(assets):
        cal_date = now - timedelta(days=60 + idx * 15)
        next_due = cal_date + timedelta(days=asset.item.calibration_interval_days or 365)
        db.add(CalibrationRecord(
            id=str(uuid.uuid4()),
            asset_id=asset.id,
            recorded_by_id=admin.id,
            certificate_number=f"CAL-{cal_date.strftime('%Y%m')}-{count+1:04d}",
            performed_at=cal_date.date(),
            due_at=next_due.date(),
            performed_by=admin.name,
            calibration_lab=cal_labs[idx % len(cal_labs)],
            result="pass",
            as_found_condition="within_tolerance",
            as_left_condition="within_tolerance",
            notes="Demo calibration record",
        ))
        count += 1

    await db.commit()
    logger.info(f"Added {count} calibration records")
    return count


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_add_data():
    logger.info("Starting sample data seed...")
    await init_db()

    async with async_session_factory() as db:
        locs_res = await db.execute(select(Location).where(Location.is_active == True))
        locations = list(locs_res.scalars().all())

        items_res = await db.execute(select(Item).where(Item.is_active == True))
        items = list(items_res.scalars().all())

        users_res = await db.execute(select(User).where(User.is_active == True))
        users = list(users_res.scalars().all())

        if not locations or not items or not users:
            logger.error("Missing base data — run seed_data.py first")
            return

        logger.info(f"Found {len(locations)} locations, {len(items)} items, {len(users)} users")

        txn_count      = await add_transactions(db, locations, items, users)
        transfer_count = await add_transfers_with_pi(db, locations, items, users)
        asset_count    = await add_serialized_assets(db, locations, items, users)
        cal_count      = await add_calibration_records(db, users)

        logger.info(
            f"Sample data complete — "
            f"transactions: {txn_count}, transfers+PIs: {transfer_count}, "
            f"assets: {asset_count}, calibrations: {cal_count}"
        )


def main():
    asyncio.run(run_add_data())


if __name__ == "__main__":
    main()
