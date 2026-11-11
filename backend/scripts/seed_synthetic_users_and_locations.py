"""
Seed synthetic users for User Management and configure locations (Hyderabad, Pune, Chennai, Bangalore)
and equipment assets with calibration records using SQLAlchemy AsyncSession.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, date, timedelta

# Ensure backend directory is in python path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import select, text
from app.db.session import async_session_factory
from app.core.security import hash_password
from app.models.location import Location
from app.models.user import User, UserRole, user_location_association
from app.models.item import Item
from app.models.asset import SerializedAsset, AssetStatus
from app.models.calibration import CalibrationRecord


async def seed_data():
    async with async_session_factory() as session:
        print("Connected to database...")
        now_dt = datetime.now()
        default_pwd_hash = hash_password("Password123!.")

        # -------------------------------------------------------------------
        # 1. Locations: Bangalore, Pune, Hyderabad, Chennai
        # -------------------------------------------------------------------
        desired_locations = [
            {
                "code": "BLR-001",
                "name": "Bangalore Head Office",
                "address": "Plot 45, Peenya Industrial Area, Phase 2",
                "city": "Bangalore",
                "state": "Karnataka",
                "country": "India",
                "postal_code": "560058",
            },
            {
                "code": "PUN-001",
                "name": "Pune Testing Facility",
                "address": "Hinjawadi Phase 2, Industrial Tech Zone",
                "city": "Pune",
                "state": "Maharashtra",
                "country": "India",
                "postal_code": "411057",
            },
            {
                "code": "HYD-001",
                "name": "Hyderabad Regional Hub",
                "address": "IDA Jeedimetla, Phase III, Sector 5",
                "city": "Hyderabad",
                "state": "Telangana",
                "country": "India",
                "postal_code": "500055",
            },
            {
                "code": "CHN-001",
                "name": "Chennai Marine Testing Yard",
                "address": "Ennore Port Expressway, Ambattur Industrial Estate",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "country": "India",
                "postal_code": "600058",
            },
        ]

        loc_map = {}  # code -> Location
        for loc_info in desired_locations:
            stmt = select(Location).where(Location.code == loc_info["code"])
            res = await session.execute(stmt)
            loc = res.scalar_one_or_none()
            if not loc:
                # Also check by name
                stmt = select(Location).where(Location.name == loc_info["name"])
                res = await session.execute(stmt)
                loc = res.scalar_one_or_none()

            if loc:
                loc.name = loc_info["name"]
                loc.code = loc_info["code"]
                loc.address = loc_info["address"]
                loc.city = loc_info["city"]
                loc.state = loc_info["state"]
                loc.postal_code = loc_info["postal_code"]
                loc.is_active = True
                print(f"  Updated location: {loc.name} ({loc.code})")
            else:
                loc = Location(
                    id=str(uuid.uuid4()),
                    name=loc_info["name"],
                    code=loc_info["code"],
                    address=loc_info["address"],
                    city=loc_info["city"],
                    state=loc_info["state"],
                    country=loc_info["country"],
                    postal_code=loc_info["postal_code"],
                    is_active=True,
                )
                session.add(loc)
                print(f"  Created location: {loc.name} ({loc.code})")

            loc_map[loc_info["code"]] = loc

        await session.flush()

        blr = loc_map["BLR-001"]
        pun = loc_map["PUN-001"]
        hyd = loc_map["HYD-001"]
        chn = loc_map["CHN-001"]
        all_loc_ids = [blr.id, pun.id, hyd.id, chn.id]

        # -------------------------------------------------------------------
        # 2. Serialized Equipment & Calibration Records for all 4 locations
        # -------------------------------------------------------------------
        stmt = select(Item).where(Item.is_serialized == True)
        res = await session.execute(stmt)
        serialized_items = {item.sku: item for item in res.scalars().all()}

        ut_item = serialized_items.get("UT-EPOCH650")
        mpt_item = serialized_items.get("MPT-YOKE-ACDC")
        cal_item = serialized_items.get("CAL-V1-BLOCK")

        admin_stmt = select(User).where(User.email == "mkumar.amiro@gmail.com")
        admin_res = await session.execute(admin_stmt)
        super_admin = admin_res.scalar_one_or_none()
        recorder_id = super_admin.id if super_admin else None

        assets_spec = [
            # Bangalore
            ("UT-EPOCH650-BLR-001", ut_item, blr.id, 450000.0, "AST-UT-BLR-01", 300),
            ("MPT-YOKE-ACDC-BLR-001", mpt_item, blr.id, 45000.0, "AST-MPT-BLR-01", 85),
            ("CAL-V1-BLOCK-BLR-001", cal_item, blr.id, 25000.0, "AST-CAL-BLR-01", 240),
            # Pune
            ("UT-EPOCH650-PUN-002", ut_item, pun.id, 450000.0, "AST-UT-PUN-02", 280),
            ("MPT-YOKE-ACDC-PUN-002", mpt_item, pun.id, 45000.0, "AST-MPT-PUN-02", 70),
            ("CAL-V1-BLOCK-PUN-002", cal_item, pun.id, 25000.0, "AST-CAL-PUN-02", 225),
            # Hyderabad
            ("UT-EPOCH650-HYD-003", ut_item, hyd.id, 450000.0, "AST-UT-HYD-03", 310),
            ("MPT-YOKE-ACDC-HYD-003", mpt_item, hyd.id, 45000.0, "AST-MPT-HYD-03", 95),
            ("CAL-V1-BLOCK-HYD-003", cal_item, hyd.id, 25000.0, "AST-CAL-HYD-03", 260),
            # Chennai
            ("UT-EPOCH650-CHN-004", ut_item, chn.id, 450000.0, "AST-UT-CHN-04", 290),
            ("MPT-YOKE-ACDC-CHN-004", mpt_item, chn.id, 45000.0, "AST-MPT-CHN-04", 65),
            ("CAL-V1-BLOCK-CHN-004", cal_item, chn.id, 25000.0, "AST-CAL-CHN-04", 210),
        ]

        print("\nSeeding Serialized Assets & Calibrations...")
        for serial, item_obj, loc_id, cost, tag, days_valid in assets_spec:
            if not item_obj:
                continue

            stmt = select(SerializedAsset).where(SerializedAsset.serial_number == serial)
            res = await session.execute(stmt)
            asset = res.scalar_one_or_none()

            if not asset:
                asset = SerializedAsset(
                    id=str(uuid.uuid4()),
                    item_id=item_obj.id,
                    serial_number=serial,
                    location_id=loc_id,
                    status=AssetStatus.IN_SERVICE,
                    acquired_at=date(2024, 1, 15),
                    cost=cost,
                    asset_tag=tag,
                )
                session.add(asset)
                print(f"  Created asset: {serial}")
            else:
                asset.location_id = loc_id
                asset.status = AssetStatus.IN_SERVICE
                asset.cost = cost
                asset.asset_tag = tag

            await session.flush()

            # Ensure calibration record exists
            cal_stmt = select(CalibrationRecord).where(CalibrationRecord.asset_id == asset.id)
            cal_res = await session.execute(cal_stmt)
            cal_rec = cal_res.scalar_one_or_none()

            performed_date = date.today() - timedelta(days=365 - days_valid)
            due_date = date.today() + timedelta(days=days_valid)

            if not cal_rec:
                cal_rec = CalibrationRecord(
                    id=str(uuid.uuid4()),
                    asset_id=asset.id,
                    recorded_by_id=recorder_id,
                    certificate_number=f"CERT-{serial}",
                    performed_at=performed_date,
                    due_at=due_date,
                    performed_by="Quality Assurance Standards",
                    calibration_lab="Amiro Precision Calibration Lab",
                    calibration_procedure="ISO-17025 / ASTM E164",
                    result="pass",
                    as_found_condition="IN_TOLERANCE",
                    as_left_condition="IN_TOLERANCE",
                )
                session.add(cal_rec)
                print(f"    Added calibration for: {serial}")

        await session.flush()

        # -------------------------------------------------------------------
        # 3. Synthetic Users for User Management
        # -------------------------------------------------------------------
        synthetic_users = [
            {
                "email": "demo.amiro@gmail.com",
                "name": "Amiro Demo",
                "role": UserRole.DEMO_USER,
                "phone": "+91 98450 00000",
                "department": "Demonstration",
                "is_active": True,
                "location_ids": all_loc_ids,
            },
            {
                "email": "rajesh.sharma@amirotech.com",
                "name": "Rajesh Sharma",
                "role": UserRole.ADMIN,
                "phone": "+91 98450 11201",
                "department": "Operations & Executive",
                "is_active": True,
                "location_ids": all_loc_ids,
            },
            {
                "email": "priya.patel@amirotech.com",
                "name": "Priya Patel",
                "role": UserRole.HEAD_OFFICE_MANAGER,
                "phone": "+91 98450 22302",
                "department": "Quality Assurance",
                "is_active": True,
                "location_ids": all_loc_ids,
            },
            {
                "email": "meera.nambiar@amirotech.com",
                "name": "Meera Nambiar",
                "role": UserRole.HEAD_OFFICE_MANAGER,
                "phone": "+91 98450 99009",
                "department": "Safety & Regulatory Compliance",
                "is_active": True,
                "location_ids": all_loc_ids,
            },
            {
                "email": "karthik.v@amirotech.com",
                "name": "Karthik Venkat",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 33403",
                "department": "NDT Inspection Services - HYD",
                "is_active": True,
                "location_ids": [hyd.id],
            },
            {
                "email": "sneha.deshmukh@amirotech.com",
                "name": "Sneha Deshmukh",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 44504",
                "department": "Industrial Testing - Pune",
                "is_active": True,
                "location_ids": [pun.id],
            },
            {
                "email": "rohan.joshi@amirotech.com",
                "name": "Rohan Joshi",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 77807",
                "department": "Ultrasonic & Radiography - Pune",
                "is_active": True,
                "location_ids": [pun.id],
            },
            {
                "email": "arun.m@amirotech.com",
                "name": "Arun Murugan",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 55605",
                "department": "Marine Inspection - Chennai",
                "is_active": True,
                "location_ids": [chn.id],
            },
            {
                "email": "divya.s@amirotech.com",
                "name": "Divya Sundaram",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 88908",
                "department": "NDT Level II Inspection - Chennai",
                "is_active": True,
                "location_ids": [chn.id],
            },
            {
                "email": "vikram.reddy@amirotech.com",
                "name": "Vikram Reddy",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 66706",
                "department": "Central Laboratory - BLR",
                "is_active": True,
                "location_ids": [blr.id],
            },
            {
                "email": "ananya.k@amirotech.com",
                "name": "Ananya Kulkarni",
                "role": UserRole.LOCATION_MANAGER,
                "phone": "+91 98450 00110",
                "department": "Field Operations - Pune",
                "is_active": False,  # Inactive user to demonstrate status filtering
                "location_ids": [pun.id],
            },
        ]

        print("\nSeeding Synthetic Users & Location Assignments...")
        for u_info in synthetic_users:
            stmt = select(User).where(User.email == u_info["email"])
            res = await session.execute(stmt)
            user = res.scalar_one_or_none()

            if not user:
                user = User(
                    id=str(uuid.uuid4()),
                    email=u_info["email"],
                    name=u_info["name"],
                    password_hash=default_pwd_hash,
                    role=u_info["role"],
                    is_active=u_info["is_active"],
                    phone=u_info["phone"],
                    department=u_info["department"],
                )
                session.add(user)
                await session.flush()
                print(f"  Created user: {user.name} ({user.email}) [{user.role}]")
            else:
                user.name = u_info["name"]
                user.role = u_info["role"]
                user.phone = u_info["phone"]
                user.department = u_info["department"]
                user.is_active = u_info["is_active"]
                await session.flush()
                print(f"  Updated user: {user.name} ({user.email}) [{user.role}]")

            # Update location assignments
            await session.execute(
                text("DELETE FROM user_locations WHERE user_id = :uid"),
                {"uid": user.id},
            )
            for lid in u_info["location_ids"]:
                await session.execute(
                    text("INSERT INTO user_locations (user_id, location_id) VALUES (:uid, :lid) ON CONFLICT DO NOTHING"),
                    {"uid": user.id, "lid": lid},
                )

        # Ensure Superadmin is also linked to all locations
        if super_admin:
            for lid in all_loc_ids:
                await session.execute(
                    text("INSERT INTO user_locations (user_id, location_id) VALUES (:uid, :lid) ON CONFLICT DO NOTHING"),
                    {"uid": super_admin.id, "lid": lid},
                )

        await session.commit()
        print("\nAll synthetic data seeded successfully into database!")


if __name__ == "__main__":
    asyncio.run(seed_data())
