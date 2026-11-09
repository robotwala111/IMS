"""
Database Seed Data

Creates the minimal baseline data for ScienceTech-IMS:
- 7 users (1 admin, 1 GM, 3 location managers, 2 location users)
- 3 locations (Bangalore HO, Mangalore Branch, Hyderabad Regional Office)
- 5 categories
- 8 items (3 serialized equipment + 5 consumables)
- 3 jobs
- 5 notifications
"""

import asyncio
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.logging import get_logger
from app.db.session import async_session_factory, init_db
from app.models.user import User, UserRole
from app.models.location import Location
from app.models.category import Category
from app.models.item import Item
from app.models.stock import Stock
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType, NotificationChannel, NotificationStatus

logger = get_logger(__name__)

SUPERADMIN_EMAIL = "mkumar.amiro@gmail.com"
SUPERADMIN_PASSWORD = "Password123!."
SUPERADMIN_NAME = "Super Admin"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

async def seed_users(db: AsyncSession) -> None:
    existing = await db.execute(select(User).where(User.email == SUPERADMIN_EMAIL))
    if existing.scalar_one_or_none():
        logger.info("Superadmin already exists, skipping")
        return

    db.add(User(
        id=str(uuid.uuid4()),
        email=SUPERADMIN_EMAIL,
        name=SUPERADMIN_NAME,
        role=UserRole.ADMIN,
        is_active=True,
        password_hash=hash_password(SUPERADMIN_PASSWORD),
    ))

    await db.commit()
    logger.info(f"Seeded superadmin: {SUPERADMIN_EMAIL}")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

async def seed_locations(db: AsyncSession) -> None:
    result = await db.execute(select(Location).limit(1))
    if result.scalar_one_or_none():
        logger.info("Locations already exist, skipping")
        return

    locations_data = [
        {"name": "Bangalore Head Office",    "code": "BLR-001", "address": "Plot 45, Peenya Industrial Area, Phase 2", "city": "Bangalore",  "state": "Karnataka",  "country": "India", "postal_code": "560058"},
        {"name": "Mangalore Branch",         "code": "MNG-001", "address": "KIADB Industrial Area, Baikampady",        "city": "Mangalore",  "state": "Karnataka",  "country": "India", "postal_code": "575011"},
        {"name": "Hyderabad Regional Office","code": "HYD-001", "address": "IDA Jeedimetla, Phase III",                "city": "Hyderabad",  "state": "Telangana",  "country": "India", "postal_code": "500055"},
    ]

    for loc in locations_data:
        db.add(Location(id=str(uuid.uuid4()), is_active=True, **loc))

    await db.commit()
    logger.info(f"Seeded {len(locations_data)} locations")


# ---------------------------------------------------------------------------
# User  Location assignments
# ---------------------------------------------------------------------------

async def assign_users_to_locations(db: AsyncSession) -> None:
    from app.models.user import user_location_association

    result = await db.execute(select(user_location_association).limit(1))
    if result.first():
        logger.info("User-location assignments exist, skipping")
        return

    users_res = await db.execute(select(User).where(User.is_active == True))
    users = list(users_res.scalars().all())

    locs_res = await db.execute(select(Location).where(Location.is_active == True))
    loc_map = {loc.name: loc.id for loc in locs_res.scalars().all()}

    email_to_locations = {
        "suresh.blr@sciencetech-ims.com": ["Bangalore Head Office"],
        "anitha.blr@sciencetech-ims.com": ["Bangalore Head Office"],
        "deepak.mng@sciencetech-ims.com": ["Mangalore Branch"],
        "vikram.hyd@sciencetech-ims.com": ["Hyderabad Regional Office"],
        "meena.hyd@sciencetech-ims.com":  ["Hyderabad Regional Office"],
    }

    assigned = 0
    for user in users:
        if user.role in (UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER):
            for loc_id in loc_map.values():
                await db.execute(user_location_association.insert().values(user_id=user.id, location_id=loc_id))
                assigned += 1
        elif user.email in email_to_locations:
            for loc_name in email_to_locations[user.email]:
                if loc_name in loc_map:
                    await db.execute(user_location_association.insert().values(user_id=user.id, location_id=loc_map[loc_name]))
                    assigned += 1

    await db.commit()
    logger.info(f"Created {assigned} user-location assignments")


# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------

async def seed_categories(db: AsyncSession) -> None:
    result = await db.execute(select(Category).limit(1))
    if result.scalar_one_or_none():
        logger.info("Categories already exist, skipping")
        return

    categories_data = [
        {"name": "Ultrasonic Testing Equipment",         "description": "UT instruments and probes"},
        {"name": "Magnetic Particle Testing Equipment",  "description": "MPT yokes, powders and inks"},
        {"name": "Liquid Penetrant Testing Supplies",    "description": "PT penetrants, developers and cleaners"},
        {"name": "Calibration Standards",                "description": "Reference blocks and calibration standards"},
        {"name": "General Consumables",                  "description": "Cleaning solvents, tapes and general supplies"},
    ]

    for cat in categories_data:
        db.add(Category(id=str(uuid.uuid4()), is_active=True, **cat))

    await db.commit()
    logger.info(f"Seeded {len(categories_data)} categories")


# ---------------------------------------------------------------------------
# Items + Stock
# ---------------------------------------------------------------------------

async def seed_sample_items(db: AsyncSession) -> None:
    result = await db.execute(select(Item).limit(1))
    if result.scalar_one_or_none():
        logger.info("Items already exist, skipping")
        return

    locs_res = await db.execute(select(Location).where(Location.is_active == True))
    locations = list(locs_res.scalars().all())

    cats_res = await db.execute(select(Category).where(Category.is_active == True))
    cat_map = {c.name: c.id for c in cats_res.scalars().all()}

    if not cat_map or not locations:
        logger.warning("Missing categories or locations, skipping item seed")
        return

    ut  = cat_map.get("Ultrasonic Testing Equipment")
    mpt = cat_map.get("Magnetic Particle Testing Equipment")
    pt  = cat_map.get("Liquid Penetrant Testing Supplies")
    cal = cat_map.get("Calibration Standards")
    con = cat_map.get("General Consumables")

    items_data = [
        # --- Serialized equipment (tracked per unit, calibration required, returnable on equipment transfers) ---
        {
            "sku": "UT-EPOCH650",
            "name": "Olympus EPOCH 650 Flaw Detector",
            "description": "Portable ultrasonic flaw detector",
            "category_id": ut,
            "unit_of_measure": "each",
            "is_serialized": True,
            "requires_calibration": True,
            "calibration_interval_days": 365,
            "standard_cost": 450000.00,
        },
        {
            "sku": "MPT-YOKE-ACDC",
            "name": "Portable Yoke — AC/DC Electromagnetic",
            "description": "Portable electromagnetic yoke for MPT inspection",
            "category_id": mpt,
            "unit_of_measure": "each",
            "is_serialized": True,
            "requires_calibration": True,
            "calibration_interval_days": 180,
            "standard_cost": 45000.00,
        },
        {
            "sku": "CAL-V1-BLOCK",
            "name": "V1 Calibration Block (IIW Type 1)",
            "description": "Standard V1 block for UT calibration",
            "category_id": cal,
            "unit_of_measure": "each",
            "is_serialized": True,
            "requires_calibration": True,
            "calibration_interval_days": 365,
            "standard_cost": 25000.00,
        },
        # --- Consumables ---
        {
            "sku": "UT-COUPLANT-500",
            "name": "Ultrasonic Couplant Gel 500ml",
            "description": "Water-based couplant gel for UT",
            "category_id": ut,
            "unit_of_measure": "bottle",
            "standard_cost": 350.00,
        },
        {
            "sku": "PT-ZL27A",
            "name": "Penetrant Dye — Zyglo ZL-27A",
            "description": "Fluorescent penetrant for crack detection",
            "category_id": pt,
            "unit_of_measure": "can",
            "has_expiry": True,
            "shelf_life_days": 365,
            "standard_cost": 950.00,
        },
        {
            "sku": "PT-SKCS",
            "name": "Cleaner/Remover — SKC-S",
            "description": "Solvent cleaner for penetrant removal",
            "category_id": pt,
            "unit_of_measure": "can",
            "has_expiry": True,
            "shelf_life_days": 365,
            "standard_cost": 650.00,
        },
        {
            "sku": "CON-IPA-1L",
            "name": "Isopropyl Alcohol 99% (1L)",
            "description": "High purity IPA for surface cleaning",
            "category_id": con,
            "unit_of_measure": "bottle",
            "standard_cost": 320.00,
        },
        {
            "sku": "MPT-POWDER-BLK",
            "name": "Magnetic Particle Powder — Black",
            "description": "Dry magnetic powder for visible light MPT inspection",
            "category_id": mpt,
            "unit_of_measure": "kg",
            "standard_cost": 850.00,
        },
    ]

    # BLR = 15 units, MNG = 8, HYD = 6
    location_stock = [15, 8, 6]

    for item_data in items_data:
        item_id = str(uuid.uuid4())
        db.add(Item(id=item_id, is_active=True, **item_data))
        await db.flush()

        for idx, loc in enumerate(locations):
            qty = location_stock[idx] if idx < len(location_stock) else 5
            db.add(Stock(
                id=str(uuid.uuid4()),
                item_id=item_id,
                location_id=loc.id,
                quantity_on_hand=qty,
                quantity_reserved=0,
                reorder_point=5,
                reorder_quantity=10,
            ))

    await db.commit()
    logger.info(f"Seeded {len(items_data)} items with stock at {len(locations)} locations")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

async def seed_jobs(db: AsyncSession) -> None:
    result = await db.execute(select(Job).limit(1))
    if result.scalar_one_or_none():
        logger.info("Jobs already exist, skipping")
        return

    users_res = await db.execute(select(User).where(User.is_active == True))
    users = list(users_res.scalars().all())

    locs_res = await db.execute(select(Location).where(Location.is_active == True))
    locations = list(locs_res.scalars().all())

    if not users or not locations:
        return

    admin      = users[0]
    technician = users[-1]
    now        = datetime.now()

    jobs_data = [
        {
            "job_number": "JOB-2026-001",
            "job_date": (now - timedelta(days=5)).date(),
            "customer": "Tata Steel Ltd",
            "job_name": "Weld Inspection — Boiler Header Joints",
            "method": "ut",
            "quantity": 24, "coverage": "100%", "total": 24,
            "accepted": 22, "reshoot": 2, "cut_films": 0,
            "person_name": technician.name,
            "assigned_to_id": technician.id,
            "location_id": locations[0].id,
            "status": JobStatus.COMPLETED,
            "completed_at": now - timedelta(days=3),
            "completed_by_id": technician.id,
            "notes": "All welds inspected per ASME V. 2 joints require re-inspection.",
            "created_by_id": admin.id,
        },
        {
            "job_number": "JOB-2026-002",
            "job_date": (now - timedelta(days=2)).date(),
            "customer": "BHEL Trichy",
            "job_name": "Turbine Blade Surface Crack Detection",
            "method": "pt",
            "quantity": 48, "coverage": "100%", "total": 48,
            "accepted": 30, "reshoot": 0, "cut_films": 0,
            "person_name": technician.name,
            "assigned_to_id": technician.id,
            "location_id": locations[1].id if len(locations) > 1 else locations[0].id,
            "status": JobStatus.IN_PROGRESS,
            "notes": "Ongoing inspection. 30 of 48 blades completed.",
            "created_by_id": admin.id,
        },
        {
            "job_number": "JOB-2026-003",
            "job_date": now.date(),
            "customer": "Indian Oil Corporation",
            "job_name": "Pipeline Girth Weld UT Inspection",
            "method": "ut",
            "quantity": 60, "coverage": "100%", "total": 60,
            "accepted": 15, "reshoot": 1, "cut_films": 0,
            "person_name": technician.name,
            "assigned_to_id": technician.id,
            "location_id": locations[2].id if len(locations) > 2 else locations[0].id,
            "status": JobStatus.IN_PROGRESS,
            "notes": "Field inspection in progress. Priority job.",
            "created_by_id": admin.id,
        },
    ]

    for job_data in jobs_data:
        db.add(Job(id=str(uuid.uuid4()), **job_data))

    await db.commit()
    logger.info(f"Seeded {len(jobs_data)} jobs")


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

async def seed_notifications(db: AsyncSession) -> None:
    result = await db.execute(select(Notification).limit(1))
    if result.scalar_one_or_none():
        logger.info("Notifications already exist, skipping")
        return

    users_res = await db.execute(select(User).where(User.is_active == True))
    users = list(users_res.scalars().all())
    if not users:
        return

    admin   = users[0]
    manager = users[2] if len(users) > 2 else admin
    now     = datetime.now()

    notifications_data = [
        {
            "notification_type": NotificationType.LOW_STOCK,
            "channel": NotificationChannel.IN_APP,
            "recipient_id": manager.id,
            "subject": "Low Stock Alert: UT Couplant Gel",
            "body": "Ultrasonic Couplant Gel 500ml at Mangalore Branch has fallen below reorder point (3 remaining, minimum 5).",
            "status": NotificationStatus.PENDING,
        },
        {
            "notification_type": NotificationType.CALIBRATION_DUE,
            "channel": NotificationChannel.IN_APP,
            "recipient_id": admin.id,
            "subject": "Calibration Due: Olympus EPOCH 650",
            "body": "Calibration for EPOCH 650 (S/N: UT-EPOCH650-BLR-001) is due in 15 days.",
            "status": NotificationStatus.PENDING,
        },
        {
            "notification_type": NotificationType.TRANSFER_REQUEST,
            "channel": NotificationChannel.IN_APP,
            "recipient_id": manager.id,
            "subject": "New Transfer + PI: TRF-2026-001",
            "body": "Transfer request TRF-2026-001 and Purchase Indent PI-2026-001 have been raised. 1 Olympus EPOCH 650 from Bangalore to Mangalore — awaiting your approval.",
            "status": NotificationStatus.SENT,
            "sent_at": now - timedelta(hours=2),
        },
        {
            "notification_type": NotificationType.MAINTENANCE_DUE,
            "channel": NotificationChannel.IN_APP,
            "recipient_id": admin.id,
            "subject": "Maintenance Due: Portable Yoke AC/DC",
            "body": "Preventive maintenance for MPT-YOKE-ACDC is overdue by 3 days.",
            "status": NotificationStatus.PENDING,
        },
        {
            "notification_type": NotificationType.SYSTEM_ALERT,
            "channel": NotificationChannel.IN_APP,
            "recipient_id": admin.id,
            "subject": "Monthly Archive Completed",
            "body": "March 2026 transactions and audit logs have been archived and emailed to admin.",
            "status": NotificationStatus.READ,
            "sent_at": now - timedelta(days=1),
            "read_at": now - timedelta(hours=18),
        },
    ]

    for notif_data in notifications_data:
        db.add(Notification(id=str(uuid.uuid4()), **notif_data))

    await db.commit()
    logger.info(f"Seeded {len(notifications_data)} notifications")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run_seed() -> None:
    logger.info("Starting database seed...")
    await init_db()

    async with async_session_factory() as db:
        await seed_users(db)
        await seed_locations(db)
        await assign_users_to_locations(db)
        await seed_categories(db)
        await seed_sample_items(db)
        await seed_jobs(db)
        await seed_notifications(db)

    logger.info("Database seed completed successfully!")


def main() -> None:
    asyncio.run(run_seed())


if __name__ == "__main__":
    main()
